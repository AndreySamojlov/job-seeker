import pytest

from job_machine.db import migrate


def _apply_all(conn):
    for m in migrate.pending(migrate.discover_migrations("db/migrations"),
                             migrate.applied_migrations(conn)):
        migrate.apply_migration(conn, m)


@pytest.mark.db
def test_state_columns_exist(db_schema):
    conn, schema = db_schema
    _apply_all(conn)
    with conn.cursor() as cur:
        cur.execute(
            "select table_name, column_name from information_schema.columns "
            "where table_schema = %s and column_name = 'state'",
            (schema,),
        )
        rows = {(t, c) for t, c in cur.fetchall()}
    assert ("vacancy", "state") in rows
    assert ("application", "state") in rows


@pytest.mark.db
def test_state_migration_idempotent(db_schema):
    conn, schema = db_schema
    _apply_all(conn)
    second = migrate.pending(migrate.discover_migrations("db/migrations"),
                             migrate.applied_migrations(conn))
    assert second == []
