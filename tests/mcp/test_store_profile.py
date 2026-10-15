import pytest

from job_machine.db import migrate
from job_machine.mcp import store


def _apply(conn):
    for m in migrate.pending(migrate.discover_migrations("db/migrations"),
                             migrate.applied_migrations(conn)):
        migrate.apply_migration(conn, m)


@pytest.mark.db
def test_load_search_profile_returns_default(db_schema):
    conn, _ = db_schema
    _apply(conn)
    conn.commit()
    p = store.load_search_profile(conn, candidate_id="andrey-s")
    assert p["candidate_id"] == "andrey-s"
    assert "remote" in p["work_mode"]
    assert isinstance(p["roles"], list)


@pytest.mark.db
def test_update_search_profile_persists(db_schema):
    conn, _ = db_schema
    _apply(conn)
    conn.commit()
    store.update_search_profile(conn, {"salary_floor": 90000,
                                       "locations": ["Europe", "Remote-EU"]},
                                 candidate_id="andrey-s")
    conn.commit()
    p = store.load_search_profile(conn, candidate_id="andrey-s")
    assert p["salary_floor"] == 90000
    assert "Remote-EU" in p["locations"]


@pytest.mark.db
def test_search_profile_scoped_and_list_candidates(db_schema):
    conn, _ = db_schema
    _apply(conn)
    with conn.cursor() as cur:
        cur.execute("insert into candidate (candidate_id, name) values ('tester-b','B')")
        cur.execute("insert into search_profile (candidate_id, roles) "
                    "values ('tester-b', '[\"QA Engineer\"]'::jsonb)")
    conn.commit()
    prof = store.load_search_profile(conn, candidate_id="tester-b")
    assert prof["candidate_id"] == "tester-b"
    assert prof["roles"] == ["QA Engineer"]
    store.update_search_profile(conn, {"locations": ["Europe"]}, candidate_id="tester-b")
    conn.commit()
    assert store.load_search_profile(conn, candidate_id="tester-b")["locations"] == ["Europe"]
    ids = {c["candidate_id"] for c in store.list_candidates(conn)}
    assert {"andrey-s", "tester-b"} <= ids


@pytest.mark.db
def test_ready_queue_and_funnel_scoped(db_schema):
    conn, _ = db_schema
    _apply(conn)
    with conn.cursor() as cur:
        cur.execute("insert into candidate (candidate_id, name) values ('tester-b','B')")
        # заявки в pre_submit_ready для обоих кандидатов на разных вакансиях
        cur.execute("insert into vacancy (company, title, vacancy_status, state) "
                    "values ('A-Co','QA','verified','verified') returning vacancy_id")
        va = cur.fetchone()[0]
        cur.execute("insert into vacancy (company, title, vacancy_status, state) "
                    "values ('B-Co','QA','verified','verified') returning vacancy_id")
        vb = cur.fetchone()[0]
        cur.execute("insert into application (vacancy_id, candidate_id, state, current_blocker) "
                    "values (%s,'andrey-s','pre_submit_ready',NULL)", (va,))
        cur.execute("insert into application (vacancy_id, candidate_id, state, current_blocker) "
                    "values (%s,'tester-b','pre_submit_ready',NULL)", (vb,))
    conn.commit()
    qa = store.query_ready_queue(conn, candidate_id="andrey-s", limit=20)
    qb = store.query_ready_queue(conn, candidate_id="tester-b", limit=20)
    assert {r["company"] for r in qa} == {"A-Co"}
    assert {r["company"] for r in qb} == {"B-Co"}
    assert store.count_by_state(conn, candidate_id="tester-b") == {
        "pre_submit_ready": 1, "outcome": {},
    }


@pytest.mark.db
def test_count_by_state_includes_employer_outcome_breakdown(db_schema):
    """outcome_status (миграция 0021) — отдельная колонка от state, не срез по
    ней в count_funnel (dashboard/store.py) уже был; тот же разрез нужен и
    per-candidate в count_by_state, иначе отказы/приглашения не видны в
    funnel_stats/Telegram /summary."""
    conn, _ = db_schema
    _apply(conn)
    with conn.cursor() as cur:
        cur.execute("insert into vacancy (company, title, canonical_url, state) "
                    "values ('A','R','u','triaged') returning vacancy_id")
        vid = cur.fetchone()[0]
        cur.execute(
            "insert into application (vacancy_id, candidate_id, state, outcome_status) "
            "values (%s,'andrey-s','submitted','rejected'),"
            "(%s,'andrey-s','submitted','interview_scheduled'),"
            "(%s,'andrey-s','submitted',NULL)",
            (vid, vid, vid))
    conn.commit()
    stats = store.count_by_state(conn, candidate_id="andrey-s")
    assert stats["submitted"] == 3
    assert stats["outcome"] == {"rejected": 1, "interview_scheduled": 1}
