import pytest

from job_machine.db import migrate


@pytest.mark.db
def test_core_schema_creates_five_tables(db_schema):
    conn, schema = db_schema
    migs = migrate.discover_migrations("db/migrations")
    for m in migrate.pending(migs, migrate.applied_migrations(conn)):
        migrate.apply_migration(conn, m)

    with conn.cursor() as cur:
        cur.execute(
            "select table_name from information_schema.tables "
            "where table_schema = %s",
            (schema,),
        )
        tables = {row[0] for row in cur.fetchall()}

    assert {
        "vacancy",
        "application",
        "artifact",
        "approval",
        "event",
        "schema_migrations",
    } <= tables


@pytest.mark.db
def test_migrations_are_idempotent(db_schema):
    conn, schema = db_schema
    migs = migrate.discover_migrations("db/migrations")
    for m in migrate.pending(migs, migrate.applied_migrations(conn)):
        migrate.apply_migration(conn, m)
    second_pass = migrate.pending(migs, migrate.applied_migrations(conn))
    assert second_pass == []
