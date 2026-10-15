import pytest

from job_machine.db import migrate
from tests.conftest import apply_migrations


@pytest.mark.db
def test_state_columns_exist(db_schema):
    conn, schema = db_schema
    apply_migrations(conn)
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
    apply_migrations(conn)
    second = migrate.pending(migrate.discover_migrations("db/migrations"),
                             migrate.applied_migrations(conn))
    assert second == []


@pytest.mark.db
def test_agent_fill_pending_state_allowed(db_schema):
    """agent_fill_pending — легальное каноническое состояние: код не добил форму,
    страница передана агенту. Констрейнт 0021 обязан его пропускать."""
    conn, _ = db_schema
    apply_migrations(conn)
    with conn.cursor() as cur:
        # conrelid = 'application'::regclass resolves via the connection's
        # search_path (set to the isolated temp schema by db_schema), not a
        # bare conname filter — job_machine_test carries a persistent public
        # schema plus leftover temp schemas from crashed runs, all with a
        # same-named constraint, so an unqualified lookup can return an
        # unrelated schema's (stale) constraint definition instead of this
        # test's own.
        cur.execute(
            "select pg_get_constraintdef(oid) from pg_constraint "
            "where conrelid = 'application'::regclass "
            "and conname='application_state_canonical_chk'")
        row = cur.fetchone()
    assert row is not None
    assert "agent_fill_pending" in row[0]
