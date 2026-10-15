import pytest

from job_machine.db import migrate
from job_machine.package import artifacts, store
from job_machine.package.models import (
    DisclosedAnswer, PackageManifest, ResumeArtifact,
)


def _apply(conn):
    for m in migrate.pending(migrate.discover_migrations("db/migrations"),
                             migrate.applied_migrations(conn)):
        migrate.apply_migration(conn, m)


def _seed_application(conn, blocker=None, company="Acme", role="QA Lead", with_resume=True,
                      candidate_id="andrey-s"):
    """vacancy(triaged) + application(needs_package). Optionally attach a generated résumé."""
    with conn.cursor() as cur:
        cur.execute(
            "insert into vacancy (company, title, canonical_url, ats_family, "
            "vacancy_status, state) values (%s,%s,%s,'greenhouse','triaged','triaged') "
            "returning vacancy_id", (company, role, f"https://{company}/apply"))
        vid = cur.fetchone()[0]
        cur.execute(
            "insert into application (vacancy_id, candidate_id, verdict, package_status, "
            "current_blocker, state) values (%s,%s,'apply','none',%s,'needs_package') "
            "returning application_id", (vid, candidate_id, blocker))
        aid = cur.fetchone()[0]
        if with_resume:
            cur.execute(
                "insert into artifact (application_id, artifact_type, path_or_uri, content_hash) "
                "values (%s,'resume','/data/resumes/x/resume.pdf','rh') returning artifact_id",
                (aid,))
            rid = cur.fetchone()[0]
            cur.execute("update application set resume_artifact_id=%s where application_id=%s",
                        (rid, aid))
    return str(aid)


@pytest.mark.db
def test_pull_excludes_missing_fact_and_non_needs_package(db_schema):
    conn, _ = db_schema
    _apply(conn)
    ok = _seed_application(conn, blocker=None, company="Good")
    _seed_application(conn, blocker="missing_fact", company="Blocked")  # mandated gate
    _seed_application(conn, blocker=None, company="NoResume", with_resume=False)  # not ready
    conn.commit()
    rows = store.pull_needs_package(conn, limit=10)
    ids = {r["application_id"] for r in rows}
    assert ok in ids
    assert len(rows) == 1                       # only the résumé-ready, unblocked one
    assert rows[0]["company"] == "Good"
    assert rows[0]["destination_url"].startswith("https://Good")
    assert rows[0]["candidate_id"] == "andrey-s"


@pytest.mark.db
def test_pull_needs_package_reports_candidate_id_per_row(db_schema):
    """Очередь needs_package может смешивать заявки разных кандидатов — candidate_id
    обязателен в каждой строке, чтобы вызыватель мог скоупить answer-vault пер-заявочно."""
    conn, _ = db_schema
    _apply(conn)
    with conn.cursor() as cur:
        cur.execute("insert into candidate (candidate_id, name) values ('tester-b','B')")
    a_id = _seed_application(conn, company="AcmeA", candidate_id="andrey-s")
    b_id = _seed_application(conn, company="AcmeB", candidate_id="tester-b")
    conn.commit()
    rows = store.pull_needs_package(conn, limit=10)
    by_company = {r["company"]: r for r in rows}
    assert by_company["AcmeA"]["candidate_id"] == "andrey-s"
    assert by_company["AcmeA"]["application_id"] == a_id
    assert by_company["AcmeB"]["candidate_id"] == "tester-b"
    assert by_company["AcmeB"]["application_id"] == b_id


@pytest.mark.db
def test_pull_needs_package_filters_by_candidate_id(db_schema):
    """Скоуп по кандидату: указан candidate_id → выбираются ТОЛЬКО его заявки. Без
    этого старший бэклог одного кандидата затеняет очередь другого (баг сессии 03.07:
    64 needs_package Андрея не давали дойти до 10 заявок Дарьи в общей FIFO-очереди)."""
    conn, _ = db_schema
    _apply(conn)
    with conn.cursor() as cur:
        cur.execute("insert into candidate (candidate_id, name) values ('tester-b','B')")
    _seed_application(conn, company="AcmeA", candidate_id="andrey-s")
    b_id = _seed_application(conn, company="AcmeB", candidate_id="tester-b")
    conn.commit()
    rows = store.pull_needs_package(conn, limit=10, candidate_id="tester-b")
    assert [r["application_id"] for r in rows] == [b_id]
    assert all(r["candidate_id"] == "tester-b" for r in rows)


@pytest.mark.db
def test_pull_needs_package_none_candidate_id_is_global(db_schema):
    """candidate_id=None (или отсутствует) сохраняет прежнее глобальное поведение —
    n8n/auto-свип и старые вызывающие не ломаются (обратная совместимость)."""
    conn, _ = db_schema
    _apply(conn)
    with conn.cursor() as cur:
        cur.execute("insert into candidate (candidate_id, name) values ('tester-b','B')")
    _seed_application(conn, company="AcmeA", candidate_id="andrey-s")
    _seed_application(conn, company="AcmeB", candidate_id="tester-b")
    conn.commit()
    rows = store.pull_needs_package(conn, limit=10, candidate_id=None)
    assert {r["company"] for r in rows} == {"AcmeA", "AcmeB"}


def _manifest(aid):
    return PackageManifest(
        application_id=aid, company="Acme", role="QA Lead",
        destination_url="https://acme/apply",
        resume=ResumeArtifact(filename="cv.pdf", path="/x/cv.pdf", content_hash="rh"),
        answers=[DisclosedAnswer(field="English", value="B2")], consents=[], warnings=[],
        answers_hash="ah", consents_hash="ch", payload_hash="ph")


@pytest.mark.db
def test_record_package_sets_state_hashes_artifacts_event(db_schema):
    conn, _ = db_schema
    _apply(conn)
    aid = _seed_application(conn)
    conn.commit()
    resume = artifacts.select_resume(conn, aid)
    m = _manifest(aid)
    m.resume = resume                            # bound to the generated artifact
    descs = [
        {"artifact_type": "approval_summary", "path": "/a/s.md", "content_hash": "sh"},
        {"artifact_type": "manifest", "path": "/a/m.json", "content_hash": "mh"},
    ]
    store.record_package(conn, m, descs)
    conn.commit()
    with conn.cursor() as cur:
        cur.execute("select package_status, state, answers_hash, consents_hash, "
                    "payload_hash, resume_artifact_id from application "
                    "where application_id=%s", (aid,))
        ps, st, ah, ch, ph, rid = cur.fetchone()
        assert (ps, st, ah, ch, ph) == ("package_ready", "package_ready", "ah", "ch", "ph")
        assert rid is not None
        cur.execute("select artifact_type from artifact where artifact_id=%s", (rid,))
        assert cur.fetchone()[0] == "resume"
        cur.execute("select count(*) from artifact where application_id=%s", (aid,))
        assert cur.fetchone()[0] == 3            # generated résumé + summary + manifest (no dup)
        cur.execute("select payload_json from event "
                    "where event_type='application.package_ready'")
        payload = cur.fetchone()[0]
        assert payload["payload_hash"] == "ph"
        assert payload["resume"]["filename"] == "resume.pdf"
        assert "English" not in str(payload)  # сырые значения ответов НЕ в событии


@pytest.mark.db
def test_select_resume_reads_generated_artifact(db_schema):
    conn, _ = db_schema
    _apply(conn)
    aid = _seed_application(conn)
    conn.commit()
    art = artifacts.select_resume(conn, aid)
    assert art.path == "/data/resumes/x/resume.pdf"
    assert art.content_hash == "rh"
    assert art.filename == "resume.pdf"
