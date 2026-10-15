import pytest

from job_machine.db import migrate
from job_machine.triage import recompute_fit, store
from job_machine.triage.models import HardRequirementMatch, TriageVerdict


def _apply(conn):
    for m in migrate.pending(migrate.discover_migrations("db/migrations"),
                             migrate.applied_migrations(conn)):
        migrate.apply_migration(conn, m)


@pytest.mark.db
def test_recompute_updates_score_and_emits_event(db_schema):
    conn, _ = db_schema
    _apply(conn)
    with conn.cursor() as cur:
        cur.execute("insert into candidate (candidate_id, name, active) "
                    "values ('andrey-s','A', true) on conflict do nothing")
        cur.execute(
            "insert into search_profile (candidate_id, roles, locations, seniority_band) "
            "values ('andrey-s','[\"QA\"]'::jsonb,'[\"Germany\"]'::jsonb,'senior') "
            "on conflict (candidate_id) do nothing")
        cur.execute(
            "insert into vacancy (source, source_url, canonical_url, title, location, "
            "vacancy_status, state, verified_at) values ('greenhouse','u','c',"
            "'Senior QA Engineer','Berlin, Germany','verified','verified',now()) "
            "returning vacancy_id")
        vid = cur.fetchone()[0]
    v = TriageVerdict(vacancy_id=str(vid), verdict="apply", fit_summary="ok",
                      hard_requirements=[HardRequirementMatch(requirement="qa", status="strong")])
    store.apply_verdict(conn, v, "andrey-s")
    conn.commit()
    # обнулить, чтобы увидеть эффект пересчёта
    with conn.cursor() as cur:
        cur.execute("update triage_result set fit_score=NULL, fit_band=NULL "
                    "where candidate_id='andrey-s' and vacancy_id=%s", (vid,))
    conn.commit()
    n = recompute_fit.recompute(conn, "andrey-s")
    assert n == 1
    with conn.cursor() as cur:
        cur.execute("select fit_score, fit_band from triage_result "
                    "where candidate_id='andrey-s' and vacancy_id=%s", (vid,))
        fs, band = cur.fetchone()
        assert isinstance(fs, int) and band in {"A", "B", "C", "D"}
        cur.execute("select count(*) from event where event_type='application.fit_scored'")
        assert cur.fetchone()[0] == 1


@pytest.mark.db
def test_recompute_skips_rows_without_requirements(db_schema):
    """Строки gate-skip (record_quick_skip) не имеют разбора требований — скорить
    нечего. Именно они породили 577 ложных band A: скор считался от title и гео."""
    conn, _ = db_schema
    _apply(conn)
    with conn.cursor() as cur:
        cur.execute("insert into candidate (candidate_id, name, active) "
                    "values ('c1','C', true) on conflict do nothing")
        cur.execute(
            "insert into search_profile (candidate_id, roles, locations, seniority_band) "
            "values ('c1','[\"QA\"]'::jsonb,'[\"Germany\"]'::jsonb,'senior') "
            "on conflict (candidate_id) do nothing")
        cur.execute(
            "insert into vacancy (source, source_url, canonical_url, title, location, "
            "vacancy_status, state, verified_at) values ('greenhouse','u2','c2',"
            "'QA Lead','Berlin, Germany','verified','verified',now()) "
            "returning vacancy_id")
        vid = cur.fetchone()[0]
    store.record_quick_skip(conn, "c1", vid, "role_family")
    conn.commit()

    assert recompute_fit.recompute(conn, "c1") == 0
    with conn.cursor() as cur:
        cur.execute("select fit_score, fit_score_version from triage_result "
                    "where candidate_id='c1' and vacancy_id=%s", (vid,))
        score, version = cur.fetchone()
    assert score is None and version is None


@pytest.mark.db
def test_recompute_preserves_v2_facts(db_schema):
    """Ревью 2026-08-15 (находка 1): пересчёт обязан восстановить факты v2 из
    triage_result.fit_facts. Раньше он пересобирал вердикт без них, три вектора из
    семи обнулялись, и штатный пересчёт после смены весов ронял бэнд у всей очереди."""
    conn, _ = db_schema
    _apply(conn)
    with conn.cursor() as cur:
        cur.execute("insert into candidate (candidate_id, name, active) "
                    "values ('c2','C', true) on conflict do nothing")
        cur.execute(
            "insert into search_profile (candidate_id, roles, locations, seniority_band, "
            "hands_on_band, domains) values ('c2','[\"QA\"]'::jsonb,'[\"Europe\"]'::jsonb,"
            "'senior','deep','[\"gaming\"]'::jsonb) on conflict (candidate_id) do nothing")
        cur.execute("insert into cloud_skill (candidate_id, name) values ('c2','python') "
                    "on conflict do nothing")
        cur.execute(
            "insert into vacancy (source, source_url, canonical_url, title, location, "
            "work_mode, vacancy_status, state, verified_at) values ('greenhouse','u3','c3',"
            "'Senior QA Engineer','Berlin, Germany','remote','verified','verified',now()) "
            "returning vacancy_id")
        vid = cur.fetchone()[0]
    v = TriageVerdict(
        vacancy_id=str(vid), verdict="apply", fit_summary="ok",
        hard_requirements=[HardRequirementMatch(requirement="qa", status="strong")],
        hands_on={"required_level": "light"}, domain={"industry": "gaming"},
        stack={"required": True, "technologies": ["Python"]})
    store.apply_verdict(conn, v, "c2")
    conn.commit()
    with conn.cursor() as cur:
        cur.execute("select fit_breakdown->'vectors' from triage_result "
                    "where candidate_id='c2' and vacancy_id=%s", (vid,))
        before = cur.fetchone()[0]
    assert before["hands_on"] == 100 and before["domain"] == 100 and before["stack"] == 100

    assert recompute_fit.recompute(conn, "c2") == 1
    with conn.cursor() as cur:
        cur.execute("select fit_breakdown->'vectors', fit_band from triage_result "
                    "where candidate_id='c2' and vacancy_id=%s", (vid,))
        after, band = cur.fetchone()
    assert after == before, "пересчёт при тех же весах обязан быть идемпотентным"
