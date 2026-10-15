import pytest

from job_machine.db import migrate
from job_machine.resume import service, store


def _apply(conn):
    for m in migrate.pending(migrate.discover_migrations("db/migrations"),
                             migrate.applied_migrations(conn)):
        migrate.apply_migration(conn, m)


def _seed_cloud(conn, candidate_id="andrey-s"):
    from job_machine.cloud.models import (
        CloudAchievement, CloudPosition, CloudSkill, ExperienceCloud,
    )
    from job_machine.cloud.store import upsert_cloud
    upsert_cloud(conn, ExperienceCloud(
        positions=[CloudPosition(pid="P-01", company="NSD", title="Head of QA / IT Delivery Leader",
                                 start="2024-09", end="present", location="Moscow")],
        achievements=[CloudAchievement(aid="A-04", pid="P-01", text="Throughput delivered",
                                       metric="15,000 test-hours", status="verified")],
        skills=[CloudSkill(name="QA & test strategy", category="skill", framing="Expert")]),
        candidate_id=candidate_id)


def _seed_app(conn, role="QA Lead", candidate_id="andrey-s"):
    with conn.cursor() as cur:
        cur.execute("insert into vacancy (company, title, canonical_url, vacancy_status, state) "
                    "values ('Acme',%s,'https://acme/apply','triaged','triaged') "
                    "returning vacancy_id", (role,))
        vid = cur.fetchone()[0]
        cur.execute("insert into application (vacancy_id, verdict, package_status, state, "
                    "candidate_id) values (%s,'apply','none','needs_package',%s) "
                    "returning application_id", (vid, candidate_id))
        return str(cur.fetchone()[0])


class _StubPdf:
    def __init__(self):
        self.last_html = None

    def render(self, html):
        self.last_html = html
        return b"%PDF-1.4 stub"

    def close(self):
        pass


@pytest.mark.db
def test_run_resume_generates_and_records(tmp_path, db_schema):
    conn, _ = db_schema
    _apply(conn)
    _seed_cloud(conn)
    aid = _seed_app(conn)
    conn.commit()
    pdf = _StubPdf()
    n = service.run_resume(conn, pdf, str(tmp_path), limit=10)
    assert n == 1
    assert "Head of QA" in pdf.last_html
    # résumé recorded → no longer pending
    assert store.pull_needs_resume(conn, limit=10) == []
    with conn.cursor() as cur:
        cur.execute("select resume_artifact_id from application where application_id=%s", (aid,))
        assert cur.fetchone()[0] is not None
    # file written
    import os
    cur_art = conn.cursor()
    cur_art.execute("select path_or_uri from artifact where application_id=%s", (aid,))
    assert os.path.isfile(cur_art.fetchone()[0])


@pytest.mark.db
def test_run_resume_scopes_cloud_and_name(tmp_path, db_schema):
    conn, _ = db_schema
    _apply(conn)
    with conn.cursor() as cur:
        cur.execute("insert into candidate (candidate_id, name) values ('tester-b','Ivan Testov')")
    _seed_cloud(conn, candidate_id="tester-b")
    aid = _seed_app(conn, candidate_id="tester-b")
    conn.commit()
    pdf = _StubPdf()
    n = service.run_resume(conn, pdf, str(tmp_path), limit=10)
    assert n == 1
    assert "<h1>Ivan Testov</h1>" in pdf.last_html
    with conn.cursor() as cur:
        cur.execute("select path_or_uri from artifact where application_id=%s", (aid,))
        path = cur.fetchone()[0]
    assert "tester-b" in path
    # Regression-guard on bug 1: "tester-b" has no entries in resume_headlines.json,
    # role "QA Lead" matches andrey-s's keywords ("qa") — but the canned phrase must
    # NOT leak into another candidate's résumé (§3).
    assert "Quality Engineering Leader" not in pdf.last_html
    assert "Head of QA / IT Delivery Leader" in pdf.last_html   # honest fallback (real title)


@pytest.mark.db
def test_apply_phrasing_verifies_then_records(tmp_path, db_schema):
    conn, _ = db_schema
    _apply(conn)
    _seed_cloud(conn)
    aid = _seed_app(conn)
    conn.commit()
    from job_machine.resume.models import PhrasedBullet, ResumePhrasing
    phr = ResumePhrasing(application_id=aid, bullets=[
        PhrasedBullet(aid="A-04", phrased_text="Owned delivery of 15,000 test-hours")])
    art = service.apply_phrasing(conn, _StubPdf(), str(tmp_path), phr)
    conn.commit()
    assert art is not None and art.content_hash
    assert store.pull_one_for_resume(conn, aid) is None     # idempotent: now has résumé


@pytest.mark.db
def test_apply_phrasing_unknown_application_returns_none(tmp_path, db_schema):
    conn, _ = db_schema
    _apply(conn)
    conn.commit()
    import uuid as _uuid
    from job_machine.resume.models import ResumePhrasing
    out = service.apply_phrasing(conn, _StubPdf(), str(tmp_path),
                                 ResumePhrasing(application_id=str(_uuid.uuid4()), bullets=[]))
    assert out is None
