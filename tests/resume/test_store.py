import pytest

from job_machine.db import migrate
from job_machine.package.models import ResumeArtifact
from job_machine.resume import store


def _apply(conn):
    for m in migrate.pending(migrate.discover_migrations("db/migrations"),
                             migrate.applied_migrations(conn)):
        migrate.apply_migration(conn, m)


def _seed_app(conn, company="Acme", role="QA Lead", triaged=None, candidate_id="andrey-s"):
    with conn.cursor() as cur:
        cur.execute(
            "insert into vacancy (company, title, canonical_url, ats_family, "
            "vacancy_status, state) values (%s,%s,%s,'greenhouse','triaged','triaged') "
            "returning vacancy_id", (company, role, f"https://{company}/apply"))
        vid = cur.fetchone()[0]
        cur.execute(
            "insert into application (vacancy_id, verdict, package_status, current_blocker, "
            "state, candidate_id) values (%s,'apply','none',null,'needs_package',%s) "
            "returning application_id",
            (vid, candidate_id))
        aid = cur.fetchone()[0]
        if triaged is not None:
            import json
            cur.execute(
                "insert into event (entity_type, entity_id, event_type, payload_json) "
                "values ('application',%s,'application.triaged',%s)", (aid, json.dumps(triaged)))
    return str(aid)


@pytest.mark.db
def test_pull_needs_resume_returns_role_and_requirements(db_schema):
    conn, _ = db_schema
    _apply(conn)
    aid = _seed_app(conn, role="Senior QA Lead",
                    triaged={"fit_summary": "strong", "hard_requirements": [{"requirement": "automation"}]})
    conn.commit()
    rows = store.pull_needs_resume(conn, limit=10)
    assert len(rows) == 1
    assert rows[0]["application_id"] == aid
    assert rows[0]["role"] == "Senior QA Lead"
    assert rows[0]["hard_requirements"][0]["requirement"] == "automation"


@pytest.mark.db
def test_record_resume_sets_artifact_and_event_without_raw_text(db_schema):
    conn, _ = db_schema
    _apply(conn)
    aid = _seed_app(conn)
    conn.commit()
    art = ResumeArtifact(filename="resume.pdf", path="/data/resumes/x/resume.pdf",
                         content_hash="deadbeef")
    store.record_resume(conn, aid, art, headline="Head of QA", aids=["A-04", "A-03"])
    conn.commit()
    with conn.cursor() as cur:
        cur.execute("select resume_artifact_id from application where application_id=%s", (aid,))
        rid = cur.fetchone()[0]
        assert rid is not None
        cur.execute("select artifact_type, path_or_uri, content_hash from artifact "
                    "where artifact_id=%s", (rid,))
        atype, path, chash = cur.fetchone()
        assert (atype, path, chash) == ("resume", "/data/resumes/x/resume.pdf", "deadbeef")
        cur.execute("select payload_json from event where event_type='application.resume_ready'")
        payload = cur.fetchone()[0]
        assert payload["resume"]["content_hash"] == "deadbeef"
        assert payload["aids"] == ["A-04", "A-03"]
        assert "Throughput" not in str(payload)   # raw bullet text never logged


@pytest.mark.db
def test_pull_excludes_application_with_resume_already(db_schema):
    conn, _ = db_schema
    _apply(conn)
    aid = _seed_app(conn)
    conn.commit()
    art = ResumeArtifact(filename="r.pdf", path="/d/r.pdf", content_hash="h")
    store.record_resume(conn, aid, art, headline="H", aids=["A-01"])
    conn.commit()
    assert store.pull_needs_resume(conn, limit=10) == []     # already has résumé → skipped
    assert store.pull_one_for_resume(conn, aid) is None
