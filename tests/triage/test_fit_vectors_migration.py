import pytest


@pytest.mark.db
def test_migration_adds_fit_vector_columns(migrated):
    conn, _ = migrated
    with conn.cursor() as cur:
        cur.execute("select column_name from information_schema.columns "
                    "where table_name='triage_result'")
        tr = {r[0] for r in cur.fetchall()}
        cur.execute("select column_name from information_schema.columns "
                    "where table_name='search_profile'")
        sp = {r[0] for r in cur.fetchall()}
    assert {"eligibility", "capped_by"} <= tr
    assert {"hands_on_band", "domains"} <= sp


@pytest.mark.db
def test_migration_adds_fit_facts_column(migrated):
    """Ревью 2026-08-15: без персиста фактов recompute_fit обнулял три вектора."""
    conn, _ = migrated
    with conn.cursor() as cur:
        cur.execute("select column_name from information_schema.columns "
                    "where table_name='triage_result' and column_name='fit_facts'")
        assert cur.fetchone() is not None
