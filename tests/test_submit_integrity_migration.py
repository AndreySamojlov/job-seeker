import pytest

from job_machine.db import migrate


def _apply(conn):
    for m in migrate.pending(migrate.discover_migrations("db/migrations"),
                             migrate.applied_migrations(conn)):
        migrate.apply_migration(conn, m)


@pytest.mark.db
def test_final_apply_url_column_added_nullable(db_schema):
    conn, _ = db_schema
    _apply(conn)
    with conn.cursor() as cur:
        cur.execute(
            "select is_nullable from information_schema.columns "
            "where table_name='application' and column_name='final_apply_url' "
            "and table_schema=current_schema()")
        row = cur.fetchone()
    assert row is not None, "application.final_apply_url missing"
    assert row[0] == "YES"
