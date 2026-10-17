"""Isolated operating-control rehearsal; execute only via guarded DB runner."""
import json
import os
from types import SimpleNamespace
from uuid import uuid4

import httpx
import psycopg
import pytest
from psycopg import sql

from tests.conftest import apply_migrations

pytestmark = pytest.mark.db


def test_auto_cycle_control_rehearsal_preserves_results_and_suppresses_calls(
    db_schema, monkeypatch, caplog, capsys
):
    from job_machine.pipeline import auto
    from job_machine.remote_readiness import control_store, intake_store, store
    from job_machine.remote_readiness import __main__ as readiness_cli
    from job_machine.remote_readiness.settings import ReadinessSettings

    conn, schema = db_schema
    apply_migrations(conn)
    monkeypatch.setattr(
        auto, "_readiness_settings_from_env",
        lambda: ReadinessSettings(enabled=True, intake_batch_limit=1, jev_batch_limit=1),
    )
    monkeypatch.setenv("RWR_ENABLED", "true")
    monkeypatch.setenv("TYPESAFE_API_KEY", "RWR_SECRET_SENTINEL_8b21")
    monkeypatch.setattr(auto.discovery_service, "run_discovery_multi",
                        lambda *_: SimpleNamespace(inserted=0))
    monkeypatch.setattr(auto.discovery_service, "run_verify",
                        lambda *_: SimpleNamespace(verified=0))
    monkeypatch.setattr(auto.fit_preparation, "run_once", lambda *_, **__: "idle")
    monkeypatch.setattr(auto.fit_worker, "run_once", lambda *_, **__: "idle")
    monkeypatch.setattr(auto.mcp_store, "list_candidates", lambda *_: [])
    monkeypatch.setattr(auto, "_pull_needs_resume", lambda *_: [])
    monkeypatch.setattr(auto.package_service, "run_package_build", lambda *_: 0)
    monkeypatch.setattr(auto.fill_service, "run_fill",
                        lambda *_: SimpleNamespace(pre_submit_ready=0))

    first_id, queued_id = uuid4(), uuid4()
    source_text = "Remote Europe; synthetic source-text sentinel RWR_SOURCE_71f9."
    api_secret = "RWR_SECRET_SENTINEL_8b21"
    provider_sentinel = "RWR_PROVIDER_BODY_SENTINEL_f032"
    conn.execute(
        """insert into vacancy(vacancy_id,source_url,ats_family,title,work_mode,
                               vacancy_status,verified_at)
           values (%s,%s,'synthetic','RWR first synthetic','remote','verified',now())""",
        (first_id, "https://synthetic.invalid/job/first"),
    )
    assert control_store.set_enabled(conn, True, actor="synthetic-rehearsal")
    conn.commit()

    ats_calls = []

    class FakeATS:
        def check_job(self, url):
            ats_calls.append(("check", url))
            return "live"

        def fetch_content(self, url):
            ats_calls.append(("fetch", url))
            return f"<p>{source_text}</p>"

        def close(self):
            pass

    jev_requests = []

    def fake_jev(request):
        jev_requests.append(request)
        fraction = 0.3141592653589793 if len(jev_requests) == 1 else 0.75
        return httpx.Response(200, json={
            "model": "jev-1.13.0",
            "answers": {"remote_work_readiness": {"type": "noul", "noul": fraction}},
            "debug": provider_sentinel,
        })

    def connect_worker():
        worker_conn = psycopg.connect(os.environ["DATABASE_URL"])
        worker_conn.execute(sql.SQL("set search_path to {}").format(sql.Identifier(schema)))
        return worker_conn

    monkeypatch.setattr(readiness_cli, "connect", connect_worker)

    client = httpx.Client(transport=httpx.MockTransport(fake_jev))

    def cycle():
        return auto.run_auto_cycle(
            conn,
            llm=object(), browser=object(), pdf=object(), discovery_client=object(),
            sources=[], limit=1, conn_factory=connect_worker,
            fit_client=client, fit_api_key="synthetic-fit-key",
            readiness_client=client, readiness_api_key=api_secret,
            readiness_client_factory=lambda _ats: FakeATS(),
        )

    try:
        first = cycle()
        assert first.readiness_enabled is True
        assert first.readiness_prepared == 1
        assert first.readiness_completed == 1
        first_saved = conn.execute(
            """select status,value,payload_hash,model,rubric_version,payload,completed_at
               from remote_work_readiness_job where vacancy_id=%s""",
            (first_id,),
        ).fetchone()
        assert first_saved is not None
        assert first_saved[0] == "completed"
        assert first_saved[1] == 0.3141592653589793
        assert isinstance(first_saved[2], str) and len(first_saved[2]) == 64
        assert first_saved[3:5] == ("jev-1.13.0", "rwr-1")
        assert first_saved[5]["state"]["job_text"] == source_text
        assert first_saved[6] is not None
        assert len(ats_calls) == 2
        assert len(jev_requests) == 1

        conn.execute(
            """insert into vacancy(vacancy_id,source_url,ats_family,title,work_mode,
                                   vacancy_status,verified_at)
               values (%s,%s,'synthetic','RWR queued synthetic','hybrid','verified',now())""",
            (queued_id, "https://synthetic.invalid/job/queued"),
        )
        conn.execute("insert into remote_work_readiness_intake(vacancy_id) values (%s)", (queued_id,))
        assert control_store.set_enabled(conn, False, actor="synthetic-rehearsal") is False
        conn.commit()
        queued_before = conn.execute(
            "select status,attempts from remote_work_readiness_intake where vacancy_id=%s",
            (queued_id,),
        ).fetchone()
        assert queued_before == ("pending", 0)

        caplog.clear()
        disabled = cycle()
        assert disabled.readiness_enabled is False
        assert disabled.readiness_enqueued == 0
        assert disabled.readiness_prepared == 0
        assert disabled.readiness_completed == 0
        assert len(ats_calls) == 2
        assert len(jev_requests) == 1
        assert conn.execute(
            "select status,attempts from remote_work_readiness_intake where vacancy_id=%s",
            (queued_id,),
        ).fetchone() == queued_before
        assert readiness_cli.main(["status"]) == 0
        disabled_status = capsys.readouterr().out
        disabled_diagnostics = json.loads(disabled_status)
        assert disabled_diagnostics["enabled"] is False
        assert disabled_diagnostics["control_enabled"] is False
        assert disabled_diagnostics["intake_counts"]["pending"] == 1
        first_while_disabled = conn.execute(
            """select status,value,payload_hash,model,rubric_version,payload,completed_at
               from remote_work_readiness_job where vacancy_id=%s""",
            (first_id,),
        ).fetchone()
        assert first_while_disabled == first_saved

        assert control_store.set_enabled(conn, True, actor="synthetic-rehearsal") is True
        assert readiness_cli.main(["rearm-intake", "--vacancy-id", str(first_id)]) == 0
        assert json.loads(capsys.readouterr().out) == {"resumed": False}
        assert readiness_cli.main(["resume-blocked", "--vacancy-id", str(first_id)]) == 0
        assert json.loads(capsys.readouterr().out) == {"resumed": False}
        assert intake_store.rearm_blocked(conn, first_id, now=first_saved[6]) is False
        assert store.rearm_blocked(conn, first_id, now=first_saved[6]) is False
        conn.commit()
        enabled_again = cycle()
        assert enabled_again.readiness_enabled is True
        assert enabled_again.readiness_prepared == 1
        assert enabled_again.readiness_completed == 1
        assert len(ats_calls) == 4
        assert len(jev_requests) == 2

        first_after_reenable = conn.execute(
            """select status,value,payload_hash,model,rubric_version,payload,completed_at
               from remote_work_readiness_job where vacancy_id=%s""",
            (first_id,),
        ).fetchone()
        assert first_after_reenable == first_saved
        assert conn.execute(
            "select status,value,model,rubric_version from remote_work_readiness_job where vacancy_id=%s",
            (queued_id,),
        ).fetchone() == ("completed", 0.75, "jev-1.13.0", "rwr-1")

        diagnostics = json.dumps(
            {"summaries": [first.__dict__, disabled.__dict__, enabled_again.__dict__],
             "logs": caplog.text, "status": disabled_status},
            ensure_ascii=True,
        )
        for sentinel in (source_text, api_secret, provider_sentinel):
            assert sentinel not in diagnostics
    finally:
        client.close()
