import pytest

from job_machine.db import migrate


def _apply(conn):
    for m in migrate.pending(migrate.discover_migrations("db/migrations"),
                             migrate.applied_migrations(conn)):
        migrate.apply_migration(conn, m)


@pytest.mark.db
def test_gate_threshold_columns_added(db_schema):
    conn, _ = db_schema
    _apply(conn)
    with conn.cursor() as cur:
        cur.execute(
            "select column_name, is_nullable from information_schema.columns "
            "where table_name='search_profile' and table_schema=current_schema() "
            "and column_name in ('seniority_band','company_daily_cap') "
            "order by column_name")
        rows = dict(cur.fetchall())
    assert rows.get("seniority_band") == "YES"
    assert rows.get("company_daily_cap") == "YES"


@pytest.mark.db
def test_andrey_backfill(db_schema):
    conn, _ = db_schema
    _apply(conn)
    with conn.cursor() as cur:
        cur.execute("select seniority_band, company_daily_cap from search_profile "
                    "where candidate_id='andrey-s'")
        row = cur.fetchone()
    assert row == ("head", 5)
