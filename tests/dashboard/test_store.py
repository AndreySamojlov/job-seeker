import pytest

from job_machine.db import migrate
from job_machine.dashboard import store


def _apply(conn):
    for m in migrate.pending(migrate.discover_migrations("db/migrations"),
                             migrate.applied_migrations(conn)):
        migrate.apply_migration(conn, m)


@pytest.mark.db
def test_count_funnel_groups_vacancy_and_application(db_schema):
    conn, _ = db_schema
    _apply(conn)
    with conn.cursor() as cur:
        cur.execute("insert into vacancy (company, title, canonical_url, state) "
                    "values ('Acme','QA','https://a/1','discovered')")
        cur.execute("insert into vacancy (company, title, canonical_url, state) "
                    "values ('Globex','QA','https://a/2','verified')")
        cur.execute("insert into vacancy (company, title, canonical_url, state) "
                    "values ('Initech','QA','https://a/3','triaged') "
                    "returning vacancy_id")
        vid = cur.fetchone()[0]
        cur.execute("insert into application (vacancy_id, candidate_id, state) "
                    "values (%s,'andrey-s','package_ready')", (vid,))
    conn.commit()
    out = store.count_funnel(conn)
    assert out["vacancy"]["discovered"] == 1
    assert out["vacancy"]["verified"] == 1
    assert out["vacancy"]["triaged"] == 1
    assert out["application"]["package_ready"] == 1


@pytest.mark.db
def test_count_funnel_reports_employer_outcomes(db_schema):
    """Исход переехал из state в outcome_status — без отдельного разреза
    отказы исчезли бы из сводки."""
    conn, _ = db_schema
    _apply(conn)
    with conn.cursor() as cur:
        cur.execute("insert into vacancy (company,title,canonical_url,state) "
                    "values ('Acme','QA','https://a/1','triaged') returning vacancy_id")
        vid = cur.fetchone()[0]
        cur.execute("insert into application (vacancy_id,candidate_id,state,outcome_status) "
                    "values (%s,'andrey-s','submitted','rejected')", (vid,))
    conn.commit()

    result = store.count_funnel(conn)

    assert result["outcome"]["rejected"] == 1


@pytest.mark.db
def test_count_blockers_groups_with_age(db_schema):
    conn, _ = db_schema
    _apply(conn)
    with conn.cursor() as cur:
        cur.execute("insert into vacancy (company, title, canonical_url, state) "
                    "values ('Acme','QA','https://a/4','triaged') returning vacancy_id")
        vid = cur.fetchone()[0]
        cur.execute("insert into application (vacancy_id, candidate_id, state, current_blocker) "
                    "values (%s,'andrey-s','fill_blocked','captcha')", (vid,))
        cur.execute("insert into application (vacancy_id, candidate_id, state, current_blocker) "
                    "values (%s,'andrey-s','fill_blocked','captcha')", (vid,))
        cur.execute("insert into application (vacancy_id, candidate_id, state, current_blocker) "
                    "values (%s,'andrey-s','fill_blocked','mfa')", (vid,))
    conn.commit()
    out = store.count_blockers(conn)
    by = {b["blocker"]: b for b in out}
    assert by["captcha"]["count"] == 2
    assert by["mfa"]["count"] == 1
    assert by["captcha"]["oldest"] is not None


@pytest.mark.db
def test_count_blockers_excludes_failed_refiled_applications(db_schema):
    """regen.refile_application deliberately leaves the old (now state='failed')
    row's current_blocker intact for diagnostic history — it must not inflate the
    live blocker dashboard forever."""
    conn, _ = db_schema
    _apply(conn)
    with conn.cursor() as cur:
        cur.execute("insert into vacancy (company, title, canonical_url, state) "
                    "values ('Acme','QA','https://a/5','triaged') returning vacancy_id")
        vid = cur.fetchone()[0]
        cur.execute("insert into application (vacancy_id, candidate_id, state, current_blocker) "
                    "values (%s,'andrey-s','failed','ambiguous')", (vid,))
    conn.commit()
    out = store.count_blockers(conn)
    by = {b["blocker"]: b for b in out}
    assert "ambiguous" not in by
