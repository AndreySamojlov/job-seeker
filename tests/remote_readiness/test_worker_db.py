"""Full Rules → Jev transport → recovery DB path with a synthetic provider response."""
from datetime import datetime, timezone
import json
import os
from uuid import uuid4

import httpx
import psycopg
import pytest
from psycopg import sql

from tests.conftest import apply_migrations

pytestmark = pytest.mark.db
NOW = datetime(2030, 1, 1, tzinfo=timezone.utc)


def test_worker_persists_jev_fraction_through_rules_and_db(db_schema):
    from job_machine.remote_readiness import rubric, store, worker
    from job_machine.remote_readiness.rules import READINESS_CATALOG, READINESS_CODE
    from cockpit_engine.rules import load_external_decision

    conn, _schema = db_schema
    apply_migrations(conn)
    vacancy_id = uuid4()
    job_text = "Remote Europe; work from any country."
    conn.execute("insert into vacancy(vacancy_id,title) values (%s,'Synthetic RWR e2e')", (vacancy_id,))
    decision = load_external_decision(READINESS_CATALOG, READINESS_CODE)
    payload = rubric.build_payload(job_text, decision=decision)
    assert store.create_job(conn, store.ReadinessInput(vacancy_id, job_text, "unknown"), payload=payload)
    conn.commit()

    observed = []
    fraction = 0.3141592653589793

    def respond(request):
        sent = json.loads(request.content)
        observed.append(sent)
        return httpx.Response(200, json={
            "model": "jev-1.13.0",
            "answers": {"remote_work_readiness": {"type": "noul", "noul": fraction}},
        })

    def connect_worker():
        worker_conn = psycopg.connect(os.environ["DATABASE_URL"])
        worker_conn.execute(sql.SQL("set search_path to {}").format(sql.Identifier(_schema)))
        return worker_conn

    client = httpx.Client(transport=httpx.MockTransport(respond))
    try:
        outcome = worker.run_once(connect_worker, client=client, api_key="synthetic-key", clock=lambda: NOW)
    finally:
        client.close()

    assert outcome == "completed"
    assert len(observed) == 1
    assert observed[0]["state"] == {"job_text": job_text, "rubric_version": "rwr-1"}
    assert set(observed[0]) == {"model", "state", "questions"}
    row = conn.execute(
        "select status,value,model,rubric_version,payload from remote_work_readiness_job where vacancy_id=%s",
        (vacancy_id,),
    ).fetchone()
    assert row == ("completed", fraction, "jev-1.13.0", "rwr-1", payload)
