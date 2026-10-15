import pytest

from job_machine.db import migrate


def _apply(conn):
    for m in migrate.pending(migrate.discover_migrations("db/migrations"),
                             migrate.applied_migrations(conn)):
        migrate.apply_migration(conn, m)


@pytest.mark.db
def test_application_has_provenance_columns(db_schema):
    conn, _ = db_schema
    _apply(conn)
    with conn.cursor() as cur:
        cur.execute(
            "select column_name from information_schema.columns "
            "where table_schema = current_schema() and table_name = 'application' "
            "and column_name in ('claims_version', 'answers_version')")
        cols = {r[0] for r in cur.fetchall()}
    assert cols == {"claims_version", "answers_version"}


@pytest.mark.db
def test_migration_is_idempotent(db_schema):
    conn, _ = db_schema
    _apply(conn)
    # повторный прогон 0008 не должен падать (add column if not exists)
    _apply(conn)
