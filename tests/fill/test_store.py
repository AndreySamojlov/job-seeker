import json
import uuid

import pytest

from job_machine.db import migrate
from job_machine.fill import store

pytestmark = pytest.mark.db


def _apply_migrations(conn):
    for m in migrate.pending(migrate.discover_migrations("db/migrations"),
                             migrate.applied_migrations(conn)):
        migrate.apply_migration(conn, m)
    conn.commit()


def _seed_package_ready(conn, *, blocker=None, with_summary=True, manifest_obj=None,
                        resume_hash="rh", candidate_id="andrey-s", url=None):
    with conn.cursor() as cur:
        cur.execute("insert into vacancy (canonical_url, company, title, ats_family) "
                    "values (%s,'Acme','Eng','greenhouse') returning vacancy_id",
                    (url or f"https://x/{candidate_id}",))
        vid = cur.fetchone()[0]
        cur.execute("insert into application (vacancy_id, candidate_id, state, current_blocker) "
                    "values (%s,%s,'package_ready',%s) returning application_id",
                    (vid, candidate_id, blocker))
        aid = cur.fetchone()[0]
        cur.execute("insert into artifact (application_id, artifact_type, path_or_uri, "
                    "content_hash) values (%s,'resume','/data/r.pdf',%s) returning artifact_id",
                    (aid, resume_hash))
        rid = cur.fetchone()[0]
        cur.execute("update application set resume_artifact_id=%s where application_id=%s",
                    (rid, aid))
        if manifest_obj is not None:
            cur.execute("insert into artifact (application_id, artifact_type, path_or_uri, "
                        "content_hash) values (%s,'manifest',%s,'mh')",
                        (aid, json.dumps(manifest_obj)))
        if with_summary:
            cur.execute("insert into artifact (application_id, artifact_type, path_or_uri, "
                        "content_hash) values (%s,'approval_summary','/data/s.md','sh')", (aid,))
    conn.commit()
    return str(aid)


def test_pull_fillable_selects_package_ready_without_blocker(db_schema):
    conn, _ = db_schema
    _apply_migrations(conn)
    aid = _seed_package_ready(conn)
    rows = store.pull_fillable(conn, 10)
    assert len(rows) == 1
    row = rows[0]
    assert row["application_id"] == aid
    assert row["resume"]["path"] == "/data/r.pdf"
    assert row["resume"]["content_hash"] == "rh"
    assert any(a["artifact_type"] == "approval_summary" for a in row["summary_artifacts"])


def test_pull_fillable_excludes_blocked(db_schema):
    conn, _ = db_schema
    _apply_migrations(conn)
    _seed_package_ready(conn, blocker="missing_fact")
    assert store.pull_fillable(conn, 10) == []


def test_pull_fillable_filters_by_candidate_id(db_schema):
    """Скоуп fill-очереди по кандидату: указан candidate_id → только его package_ready.
    Симметрично pull_needs_package — иначе fill-свип тоже затеняет кандидата с младшими
    заявками (баг сессии 03.07)."""
    conn, _ = db_schema
    _apply_migrations(conn)
    with conn.cursor() as cur:
        cur.execute("insert into candidate (candidate_id, name) values ('tester-b','B')")
    conn.commit()
    _seed_package_ready(conn, candidate_id="andrey-s")
    b_id = _seed_package_ready(conn, candidate_id="tester-b")
    rows = store.pull_fillable(conn, 10, candidate_id="tester-b")
    assert [r["application_id"] for r in rows] == [b_id]


def test_pull_fillable_none_candidate_id_is_global(db_schema):
    """candidate_id=None сохраняет прежнее глобальное поведение (n8n /fill/run без
    candidate_id продолжает свипать всех — обратная совместимость)."""
    conn, _ = db_schema
    _apply_migrations(conn)
    with conn.cursor() as cur:
        cur.execute("insert into candidate (candidate_id, name) values ('tester-b','B')")
    conn.commit()
    a_id = _seed_package_ready(conn, candidate_id="andrey-s")
    b_id = _seed_package_ready(conn, candidate_id="tester-b")
    ids = {r["application_id"] for r in store.pull_fillable(conn, 10, candidate_id=None)}
    assert ids == {a_id, b_id}


def test_load_manifest_reads_disclosed_answers(tmp_path):
    p = tmp_path / "manifest.json"
    p.write_text(json.dumps({
        "application_id": "a", "company": "Acme", "role": "Eng",
        "destination_url": "https://x/1",
        "resume": {"filename": "r.pdf", "path": "/data/r.pdf", "content_hash": "rh"},
        "answers": [{"field": "Email", "value": "a@b.com", "source": "locked"}],
        "consents": [], "warnings": [],
        "answers_hash": "ah", "consents_hash": "ch", "payload_hash": "ph",
    }), encoding="utf-8")
    m = store.load_manifest(str(p))
    assert m.destination_url == "https://x/1"
    assert m.answers[0].value == "a@b.com"


def test_record_pre_submit_ready_sets_state_and_event_without_values(db_schema):
    conn, _ = db_schema
    _apply_migrations(conn)
    aid = _seed_package_ready(conn)
    store.record_pre_submit_ready(conn, aid, filled_fields=["job_application[email]"],
                                  resume_attached=True, screenshot_path="/data/f.png")
    conn.commit()
    with conn.cursor() as cur:
        cur.execute("select state, fill_status from application where application_id=%s", (aid,))
        assert cur.fetchone() == ("pre_submit_ready", "pre_submit_ready")
        cur.execute("select event_type, payload_json from event "
                    "where entity_id=%s order by created_at desc limit 1", (aid,))
        etype, payload = cur.fetchone()
    assert etype == "application.pre_submit_ready"
    assert payload["filled_fields"] == ["job_application[email]"]
    assert "a@b.com" not in json.dumps(payload)


def test_record_fill_blocked_sets_blocker_and_event(db_schema):
    conn, _ = db_schema
    _apply_migrations(conn)
    aid = _seed_package_ready(conn)
    store.record_fill_blocked(conn, aid, "mandatory_unknown",
                              {"unmatched": ["job_application[answers_attributes][1]"]})
    conn.commit()
    with conn.cursor() as cur:
        cur.execute("select state, fill_status, current_blocker from application "
                    "where application_id=%s", (aid,))
        assert cur.fetchone() == ("fill_blocked", "blocked", "mandatory_unknown")
        cur.execute("select event_type from event where entity_id=%s "
                    "order by created_at desc limit 1", (aid,))
        assert cur.fetchone()[0] == "application.fill_blocked"


def _vacancy_of(conn, aid):
    with conn.cursor() as cur:
        cur.execute("select vacancy_id from application where application_id=%s", (aid,))
        return str(cur.fetchone()[0])


def test_pull_fillable_picks_latest_manifest_when_duplicates_exist(db_schema):
    """Reopen+repackage после фикса пути (audit 02.07 / package-worker-delegate)
    оставляет СТАРУЮ manifest-артефакт-строку рядом с новой (record не правит,
    только добавляет). Без ORDER BY select возвращает произвольный порядок —
    pull_fillable должен взять САМУЮ СВЕЖУЮ (по created_at), иначе fill ищет
    файл по устаревшему пути и падает broken_flow (No such file or directory)."""
    conn, _ = db_schema
    _apply_migrations(conn)
    aid = _seed_package_ready(conn)
    with conn.cursor() as cur:
        cur.execute(
            "insert into artifact (application_id, artifact_type, path_or_uri, "
            "content_hash, created_at) values (%s,'manifest','applications\\old\\manifest.json',"
            "'oldh', now() - interval '2 days')", (aid,))
        cur.execute(
            "insert into artifact (application_id, artifact_type, path_or_uri, "
            "content_hash, created_at) values (%s,'manifest','/data/applications/new/manifest.json',"
            "'newh', now())", (aid,))
    conn.commit()
    rows = store.pull_fillable(conn, 10)
    assert rows[0]["manifest_path"] == "/data/applications/new/manifest.json"


def test_pull_fillable_returns_vacancy_id(db_schema):
    conn, _ = db_schema
    _apply_migrations(conn)
    aid = _seed_package_ready(conn)
    rows = store.pull_fillable(conn, 10)
    assert rows[0]["vacancy_id"] == _vacancy_of(conn, aid)


def test_load_fillable_row_by_id_returns_row_regardless_of_state(db_schema):
    """resume_after_handoff вызывается когда state='fill_blocked' +
    current_blocker='handoff_manual' (не package_ready) — load_fillable_row_by_id
    НЕ фильтрует по state."""
    conn, _ = db_schema
    _apply_migrations(conn)
    aid = _seed_package_ready(conn)
    with conn.cursor() as cur:
        cur.execute("update application set state='fill_blocked', "
                    "current_blocker='handoff_manual' "
                    "where application_id=%s", (aid,))
    conn.commit()
    row = store.load_fillable_row_by_id(conn, aid)
    assert row["application_id"] == aid
    assert row["resume"]["path"] == "/data/r.pdf"


def test_load_fillable_row_by_id_none_when_missing(db_schema):
    conn, _ = db_schema
    _apply_migrations(conn)
    assert store.load_fillable_row_by_id(conn, str(uuid.uuid4())) is None


def test_load_fillable_row_by_id_picks_latest_manifest(db_schema):
    """Тот же инвариант свежего manifest, что и pull_fillable (audit 02.07)."""
    conn, _ = db_schema
    _apply_migrations(conn)
    aid = _seed_package_ready(conn)
    with conn.cursor() as cur:
        cur.execute(
            "insert into artifact (application_id, artifact_type, path_or_uri, "
            "content_hash, created_at) values (%s,'manifest','/old/manifest.json',"
            "'oldh', now() - interval '2 days')", (aid,))
        cur.execute(
            "insert into artifact (application_id, artifact_type, path_or_uri, "
            "content_hash, created_at) values (%s,'manifest','/data/new/manifest.json',"
            "'newh', now())", (aid,))
    conn.commit()
    row = store.load_fillable_row_by_id(conn, aid)
    assert row["manifest_path"] == "/data/new/manifest.json"


def test_record_destination_redirect_blocks_and_emits_dedup_signal(db_schema):
    conn, _ = db_schema
    _apply_migrations(conn)
    aid = _seed_package_ready(conn)
    vid = _vacancy_of(conn, aid)
    store.record_destination_redirect(conn, aid, vid,
                                      source_url="https://boards.greenhouse.io/a/jobs/1",
                                      final_url="https://boards.greenhouse.io/a/jobs/2")
    conn.commit()
    with conn.cursor() as cur:
        cur.execute("select state, current_blocker from application "
                    "where application_id=%s", (aid,))
        assert cur.fetchone() == ("fill_blocked", "destination_redirect")
        cur.execute("select payload_json from event where entity_id=%s "
                    "and event_type='vacancy.requisition_duplicate'", (vid,))
        payload = cur.fetchone()[0]
        assert payload["final_url"].endswith("/jobs/2")
        assert payload["application_id"] == aid


def test_record_destination_resolved_appends_artifacts_and_rebinds_hash(db_schema):
    conn, _ = db_schema
    _apply_migrations(conn)
    aid = _seed_package_ready(conn)  # уже несёт артефакты resume + approval_summary
    with conn.cursor() as cur:
        cur.execute("update application set payload_hash='OLDPH' "
                    "where application_id=%s", (aid,))
    conn.commit()
    from job_machine.package.models import PackageManifest, ResumeArtifact
    m2 = PackageManifest(application_id=aid, company="A", role="R",
                         destination_url="https://final/jobs/1",
                         resume=ResumeArtifact(filename="r", path="/r", content_hash="RH"),
                         answers=[], consents=[], warnings=[],
                         answers_hash="ah", consents_hash="ch", payload_hash="NEWPH")
    descs = [{"artifact_type": "approval_summary", "path": "/p/s.md", "content_hash": "h1"},
             {"artifact_type": "manifest", "path": "/p/m.json", "content_hash": "h2"}]
    store.record_destination_resolved(conn, aid, source_url="https://src/jobs/1",
                                      final_url="https://final/jobs/1",
                                      manifest=m2, artifact_descs=descs)
    conn.commit()
    with conn.cursor() as cur:
        cur.execute("select payload_hash, final_apply_url from application "
                    "where application_id=%s", (aid,))
        assert cur.fetchone() == ("NEWPH", "https://final/jobs/1")
        cur.execute("select count(*) from artifact where application_id=%s "
                    "and artifact_type in ('approval_summary','manifest')", (aid,))
        assert cur.fetchone()[0] == 3  # seed: 1 summary; append: summary + manifest
        cur.execute("select payload_json from event where entity_id=%s "
                    "and event_type='application.destination_resolved'", (aid,))
        p = cur.fetchone()[0]
        assert p["old_payload_hash"] == "OLDPH" and p["new_payload_hash"] == "NEWPH"
        assert p["old_url"] == "https://src/jobs/1"


def test_record_final_apply_url(db_schema):
    conn, _ = db_schema
    _apply_migrations(conn)
    aid = _seed_package_ready(conn)
    store.record_final_apply_url(conn, aid, "https://final/jobs/1")
    conn.commit()
    with conn.cursor() as cur:
        cur.execute("select final_apply_url from application where application_id=%s",
                    (aid,))
        assert cur.fetchone()[0] == "https://final/jobs/1"
