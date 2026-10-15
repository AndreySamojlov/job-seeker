import pytest

from job_machine.db import migrate
from job_machine.discovery import store as discovery_store
from job_machine.discovery.models import VacancyRecord
from job_machine.watchlist import hh_sync


def _apply_migrations(conn):
    for m in migrate.pending(migrate.discover_migrations("db/migrations"),
                             migrate.applied_migrations(conn)):
        migrate.apply_migration(conn, m)


def _insert_hh_vacancy_with_fit(conn, company, fit_band, candidate_id="andrey-s"):
    rec = VacancyRecord(
        source="hh", source_url=f"https://hh.ru/vacancy/{company}",
        canonical_url=f"https://hh.ru/vacancy/{company}", company=company,
        normalized_company=company.lower(), title="QA Lead",
        normalized_title="qa lead", location="Cyprus", work_mode="remote",
        ats_family="hh",
    )
    vacancy_id = discovery_store.upsert_vacancy(conn, rec)
    with conn.cursor() as cur:
        cur.execute(
            "insert into triage_result (candidate_id, vacancy_id, verdict, fit_band) "
            "values (%s, %s, 'apply', %s)",
            (candidate_id, vacancy_id, fit_band),
        )
    return vacancy_id


@pytest.mark.db
def test_sync_upserts_evidence_for_good_fit_band(db_schema):
    conn, _ = db_schema
    _apply_migrations(conn)
    _insert_hh_vacancy_with_fit(conn, "Acme", "A")

    result = hh_sync.sync(conn)
    conn.commit()

    assert result.synced == 1
    assert result.skipped == 0
    with conn.cursor() as cur:
        cur.execute("select count(*) from company_watchlist where company_name = 'Acme'")
        assert cur.fetchone()[0] == 1


@pytest.mark.db
def test_sync_skips_poor_fit_band(db_schema):
    conn, _ = db_schema
    _apply_migrations(conn)
    _insert_hh_vacancy_with_fit(conn, "MehCorp", "D")

    result = hh_sync.sync(conn)
    conn.commit()

    assert result.synced == 0
    with conn.cursor() as cur:
        cur.execute("select count(*) from company_watchlist")
        assert cur.fetchone()[0] == 0


@pytest.mark.db
def test_sync_is_idempotent_on_rerun(db_schema):
    conn, _ = db_schema
    _apply_migrations(conn)
    _insert_hh_vacancy_with_fit(conn, "RepeatCo", "B")

    first = hh_sync.sync(conn)
    conn.commit()
    second = hh_sync.sync(conn)
    conn.commit()

    assert first.synced == 1
    assert second.synced == 0  # уже в hh_watchlist_sync, не пере-синкается
    with conn.cursor() as cur:
        cur.execute("select evidence_count from company_watchlist where company_name = 'RepeatCo'")
        assert cur.fetchone()[0] == 1  # не задвоилось на повторном прогоне


@pytest.mark.db
def test_sync_dedups_when_multiple_candidates_rate_same_vacancy(db_schema):
    conn, _ = db_schema
    _apply_migrations(conn)
    # Insert second candidate (migrations only seed andrey-s)
    with conn.cursor() as cur:
        cur.execute(
            "insert into candidate (candidate_id, name) values (%s, %s)",
            ("daria-b", "Daria B"),
        )
    conn.commit()

    rec = VacancyRecord(
        source="hh", source_url="https://hh.ru/vacancy/DualCo",
        canonical_url="https://hh.ru/vacancy/DualCo", company="DualCo",
        normalized_company="dualco", title="QA Lead", normalized_title="qa lead",
        location="Cyprus", work_mode="remote", ats_family="hh",
    )
    vacancy_id = discovery_store.upsert_vacancy(conn, rec)
    with conn.cursor() as cur:
        cur.execute(
            "insert into triage_result (candidate_id, vacancy_id, verdict, fit_band) "
            "values (%s, %s, 'apply', %s)", ("andrey-s", vacancy_id, "A"),
        )
        cur.execute(
            "insert into triage_result (candidate_id, vacancy_id, verdict, fit_band) "
            "values (%s, %s, 'apply', %s)", ("daria-b", vacancy_id, "B"),
        )
    conn.commit()

    result = hh_sync.sync(conn)
    conn.commit()

    assert result.synced == 1  # one vacancy, not double-counted across 2 candidates
    with conn.cursor() as cur:
        cur.execute("select evidence_count from company_watchlist where company_name = 'DualCo'")
        assert cur.fetchone()[0] == 1  # upsert_evidence called exactly once, not twice
