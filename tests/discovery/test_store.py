import json

import pytest

from job_machine.db import migrate
from job_machine.discovery import store
from job_machine.discovery.models import VacancyRecord


def _apply_migrations(conn):
    for m in migrate.pending(migrate.discover_migrations("db/migrations"),
                             migrate.applied_migrations(conn)):
        migrate.apply_migration(conn, m)


def _rec(canonical="https://boards.greenhouse.io/acme/jobs/1"):
    return VacancyRecord(
        source="greenhouse",
        source_url="https://boards-api.greenhouse.io/v1/boards/acme/jobs/1",
        canonical_url=canonical, company="Acme", normalized_company="acme",
        title="Eng", normalized_title="eng", location="Remote",
        work_mode="remote", ats_family="greenhouse",
    )


@pytest.mark.db
def test_upsert_inserts_then_dedups(db_schema):
    conn, _ = db_schema
    _apply_migrations(conn)

    vid = store.upsert_vacancy(conn, _rec())
    assert vid is not None
    dup = store.upsert_vacancy(conn, _rec())
    assert dup is None  # дубль по canonical_url

    with conn.cursor() as cur:
        cur.execute("select vacancy_status, state from vacancy where vacancy_id = %s", (vid,))
        assert cur.fetchone() == ("discovered", "discovered")
        cur.execute("select count(*) from event where event_type = 'vacancy.discovered'")
        assert cur.fetchone()[0] == 1  # событие только на реальной вставке


@pytest.mark.db
def test_verify_marks_status_and_events(db_schema):
    conn, _ = db_schema
    _apply_migrations(conn)
    vid_live = store.upsert_vacancy(conn, _rec("https://boards.greenhouse.io/acme/jobs/1"))
    vid_gone = store.upsert_vacancy(conn, _rec("https://boards.greenhouse.io/acme/jobs/2"))

    store.mark_verified(conn, vid_live)
    store.mark_stale(conn, vid_gone)

    with conn.cursor() as cur:
        cur.execute("select vacancy_status, state, verified_at is not null "
                    "from vacancy where vacancy_id = %s", (vid_live,))
        assert cur.fetchone() == ("verified", "verified", True)
        cur.execute("select vacancy_status, state, verified_at is not null "
                    "from vacancy where vacancy_id = %s", (vid_gone,))
        # stale — non-lifecycle: state остаётся 'discovered'
        assert cur.fetchone() == ("stale", "discovered", True)
        cur.execute("select event_type from event order by created_at")
        types = [r[0] for r in cur.fetchall()]
    assert "vacancy.verified" in types and "vacancy.stale" in types


@pytest.mark.db
def test_pull_discovered_returns_only_discovered(db_schema):
    conn, _ = db_schema
    _apply_migrations(conn)
    vid_a = store.upsert_vacancy(conn, _rec("https://boards.greenhouse.io/acme/jobs/1"))
    vid_b = store.upsert_vacancy(conn, _rec("https://boards.greenhouse.io/acme/jobs/2"))
    store.mark_verified(conn, vid_a)

    rows = store.pull_discovered(conn, limit=10)
    ids = [r[0] for r in rows]
    assert vid_b in [str(i) for i in ids]
    assert vid_a not in [str(i) for i in ids]


@pytest.mark.db
def test_pull_discovered_includes_ats_family(db_schema):
    """run_verify должен диспатчить клиента по ats_family (иначе Ashby/Lever
    проверяются чужим client'ом — см. C-* баг застрявших Ashby-вакансий)."""
    conn, _ = db_schema
    _apply_migrations(conn)
    ashby_rec = _rec("https://jobs.ashbyhq.com/ramp/1").model_copy(
        update={"ats_family": "ashby", "source_url": "https://api.ashbyhq.com/posting-api/job-board/ramp/1"})
    store.upsert_vacancy(conn, ashby_rec)
    store.upsert_vacancy(conn, _rec("https://boards.greenhouse.io/acme/jobs/1"))

    rows = store.pull_discovered(conn, limit=10)
    families = {r[2] for r in rows}
    assert families == {"ashby", "greenhouse"}


def _rec_titled(canonical, title, normalized_title):
    r = _rec(canonical)
    return r.model_copy(update={"title": title, "normalized_title": normalized_title})


def _seed_candidate_with_roles(conn, candidate_id, roles):
    """Завести кандидата + search_profile-строку с заданными ролями (тестовый хелпер)."""
    with conn.cursor() as cur:
        cur.execute(
            "insert into candidate (candidate_id, name) values (%s, %s) "
            "on conflict (candidate_id) do nothing", (candidate_id, candidate_id))
        cur.execute(
            "insert into search_profile (candidate_id, roles) values (%s, %s::jsonb) "
            "on conflict (candidate_id) do update set roles=excluded.roles",
            (candidate_id, json.dumps(roles)))


@pytest.mark.db
def test_load_profile_role_patterns(db_schema):
    conn, _ = db_schema
    _apply_migrations(conn)
    _seed_candidate_with_roles(conn, "andrey-s", ["QA Lead", "Team Lead"])
    pats = store.load_profile_role_patterns(conn)
    assert pats == ["%qa lead%", "%team lead%"]


@pytest.mark.db
def test_load_profile_role_patterns_skips_blank_roles(db_schema):
    conn, _ = db_schema
    _apply_migrations(conn)
    _seed_candidate_with_roles(conn, "andrey-s", ["", "  ", "QA Lead"])
    pats = store.load_profile_role_patterns(conn)
    assert pats == ["%qa lead%"]


@pytest.mark.db
def test_load_profile_role_patterns_unions_across_active_candidates(db_schema):
    """Несколько активных кандидатов → union ролей."""
    conn, _ = db_schema
    _apply_migrations(conn)
    _seed_candidate_with_roles(conn, "andrey-s", ["QA Lead"])
    _seed_candidate_with_roles(conn, "second-c", ["Data Scientist"])
    pats = store.load_profile_role_patterns(conn)
    assert pats == ["%data scientist%", "%qa lead%"]


@pytest.mark.db
def test_pull_discovered_prioritizes_target_titles(db_schema):
    conn, _ = db_schema
    _apply_migrations(conn)
    vid_old = store.upsert_vacancy(conn, _rec_titled(
        "https://boards.greenhouse.io/acme/jobs/1", "Accountant", "accountant"))
    vid_new = store.upsert_vacancy(conn, _rec_titled(
        "https://boards.greenhouse.io/acme/jobs/2", "Designer", "designer"))
    vid_target = store.upsert_vacancy(conn, _rec_titled(
        "https://boards.greenhouse.io/acme/jobs/3", "QA Lead", "qa lead"))
    # разнести discovered_at явно, иначе FIFO-порядок флакает внутри одной транзакции
    with conn.cursor() as cur:
        cur.execute("update vacancy set discovered_at = now() - interval '3 days' "
                    "where vacancy_id = %s", (vid_old,))
        cur.execute("update vacancy set discovered_at = now() - interval '1 day' "
                    "where vacancy_id = %s", (vid_new,))

    rows = store.pull_discovered(conn, limit=10,
                                 priority_patterns=["%qa lead%", "%team lead%"])
    ids = [str(r[0]) for r in rows]
    assert ids[0] == vid_target          # целевая — первой
    assert ids[1:] == [vid_old, vid_new]  # остальные — прежний FIFO (старейшие первыми)

    # без паттернов — прежнее поведение (регресс-контроль)
    rows_plain = store.pull_discovered(conn, limit=10)
    assert [str(r[0]) for r in rows_plain] == [vid_old, vid_new, vid_target]
