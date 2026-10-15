import pytest

from job_machine.db import migrate
from job_machine.watchlist import store
from job_machine.watchlist.models import PostingEvidence


def _apply_migrations(conn):
    for m in migrate.pending(migrate.discover_migrations("db/migrations"),
                             migrate.applied_migrations(conn)):
        migrate.apply_migration(conn, m)


def _evidence(title="Engineer"):
    return PostingEvidence(
        title=title, url=f"https://linkedin.com/jobs/{title}",
        location="Remote", found_at="2026-07-03T00:00:00+00:00",
        explicit_global=False,
    )


@pytest.mark.db
def test_upsert_inserts_new_company(db_schema):
    conn, _ = db_schema
    _apply_migrations(conn)

    is_new = store.upsert_evidence(conn, "Acme Inc", _evidence())
    assert is_new is True

    with conn.cursor() as cur:
        cur.execute(
            "select company_name, evidence_count, jsonb_array_length(sample_postings) "
            "from company_watchlist where company_name_normalized = %s",
            ("acme inc",),
        )
        row = cur.fetchone()
    assert row == ("Acme Inc", 1, 1)


@pytest.mark.db
def test_upsert_dedups_and_increments(db_schema):
    conn, _ = db_schema
    _apply_migrations(conn)

    store.upsert_evidence(conn, "Acme Inc", _evidence("Engineer"))
    is_new = store.upsert_evidence(conn, "  ACME   INC ", _evidence("QA"))
    assert is_new is False

    with conn.cursor() as cur:
        cur.execute(
            "select company_name, evidence_count, jsonb_array_length(sample_postings) "
            "from company_watchlist where company_name_normalized = %s",
            ("acme inc",),
        )
        row = cur.fetchone()
    assert row == ("Acme Inc", 2, 2)


@pytest.mark.db
def test_sample_postings_capped_at_five(db_schema):
    conn, _ = db_schema
    _apply_migrations(conn)

    for i in range(6):
        store.upsert_evidence(conn, "Acme Inc", _evidence(f"Role{i}"))

    with conn.cursor() as cur:
        cur.execute(
            "select evidence_count, sample_postings from company_watchlist "
            "where company_name_normalized = %s",
            ("acme inc",),
        )
        count, postings = cur.fetchone()
    assert count == 6
    assert [p["title"] for p in postings] == ["Role1", "Role2", "Role3", "Role4", "Role5"]


@pytest.mark.db
def test_upsert_empty_company_is_noop(db_schema):
    conn, _ = db_schema
    _apply_migrations(conn)

    is_new = store.upsert_evidence(conn, "   ", _evidence())
    assert is_new is False

    with conn.cursor() as cur:
        cur.execute("select count(*) from company_watchlist")
        assert cur.fetchone()[0] == 0
