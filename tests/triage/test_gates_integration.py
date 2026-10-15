import pytest

from job_machine.db import migrate
from job_machine.triage import service


class FakeClient:
    def fetch_content(self, url):
        return "<p>job text</p>"


def _apply(conn):
    for m in migrate.pending(migrate.discover_migrations("db/migrations"),
                             migrate.applied_migrations(conn)):
        migrate.apply_migration(conn, m)


def _insert_vacancy(conn, company, title, url, location, work_mode="remote",
                    ats="greenhouse"):
    with conn.cursor() as cur:
        cur.execute(
            "insert into vacancy (source_url, canonical_url, company, title, "
            "location, work_mode, ats_family, vacancy_status) "
            "values (%s,%s,%s,%s,%s,%s,%s,'verified') returning vacancy_id",
            (url, url, company, title, location, work_mode, ats))
        return cur.fetchone()[0]


def _reasons(conn):
    with conn.cursor() as cur:
        cur.execute("select payload_json->>'reason' from event "
                    "where event_type='vacancy.quick_skipped'")
        return [r[0] for r in cur.fetchall()]


@pytest.mark.db
def test_gates_skip_and_pass(db_schema):
    conn, _ = db_schema
    _apply(conn)
    # search_profile.roles seed для andrey-s = ["QA","Test automation"] (0006); QA есть.
    _insert_vacancy(conn, "Figma", "Senior QA Engineer",
                    "https://boards.greenhouse.io/figma/jobs/1",
                    "San Francisco, CA")                         # geo skip
    _insert_vacancy(conn, "Acme", "(Junior) Product Manager",
                    "https://boards.greenhouse.io/acme/jobs/2", "Berlin")  # role_family skip
    _insert_vacancy(conn, "Globex", "QA Engineer",
                    "https://boards.greenhouse.io/globex/jobs/3", "Berlin")  # pass
    conn.commit()

    summary = service.build_triage_inputs(conn, FakeClient(), "andrey-s", limit=25)
    titles = {i.title for i in summary.inputs}
    assert any("qa" in (t or "").lower() for t in titles)   # EU-QA прошла
    assert not any("product manager" in (t or "").lower() for t in titles)
    assert summary.quick_skipped >= 2                        # US + PM отсеяны
    reasons = _reasons(conn)
    assert "geo_ineligible" in reasons
    assert "role_family" in reasons


@pytest.mark.db
def test_company_cap_skips_flood(db_schema):
    conn, _ = db_schema
    _apply(conn)
    # 7 QA-EU вакансий от одной компании; cap andrey-s = 5 → 2 в company_daily_cap.
    for i in range(7):
        _insert_vacancy(conn, "Flood", f"QA Engineer {i}",
                        f"https://boards.greenhouse.io/flood/jobs/{i}", "Berlin")
    conn.commit()
    summary = service.build_triage_inputs(conn, FakeClient(), "andrey-s", limit=25)
    assert len(summary.inputs) == 5
    caps = [r for r in _reasons(conn) if r == "company_daily_cap"]
    assert len(caps) == 2


@pytest.mark.db
def test_dedup_within_pass(db_schema):
    conn, _ = db_schema
    _apply(conn)
    # Один и тот же greenhouse-пост под двумя URL-шардами → второй = requisition_duplicate.
    _insert_vacancy(conn, "Acme", "QA Engineer",
                    "https://boards.greenhouse.io/acme/jobs/99", "Berlin")
    _insert_vacancy(conn, "Acme", "QA Engineer",
                    "https://job-boards.eu.greenhouse.io/acme/jobs/99?loc=x", "Berlin")
    conn.commit()
    summary = service.build_triage_inputs(conn, FakeClient(), "andrey-s", limit=25)
    assert len(summary.inputs) == 1
    assert "requisition_duplicate" in _reasons(conn)
