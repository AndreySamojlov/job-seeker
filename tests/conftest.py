import os
import uuid

import pytest

from job_machine.db import migrate
from job_machine.db.connection import connect


def assert_not_production_database(url: str) -> None:
    """Тесты создают временные схемы; в проде это уже дало 111 мусорных схем."""
    name = url.rsplit("/", 1)[-1].split("?", 1)[0]
    if name == "job_machine":
        raise RuntimeError(
            "refusing to run tests against the production database "
            "'job_machine'; point DATABASE_URL at 'job_machine_test'"
        )


def apply_migrations(conn) -> None:
    """Накатить все непринятые миграции в текущую схему.

    Тот же цикл, что уже повторяется в tests/approval/test_store.py и
    tests/test_audit.py — вынесен сюда, чтобы новые db-тесты его не копировали.
    """
    for migration in migrate.pending(
        migrate.discover_migrations("db/migrations"),
        migrate.applied_migrations(conn),
    ):
        migrate.apply_migration(conn, migration)


@pytest.fixture
def db_schema():
    """Create an isolated temp schema for a db-marked test; drop it after.

    Yields (conn, schema_name). The connection's search_path points at the
    temp schema, so migrations and queries run inside it.
    """
    assert_not_production_database(os.environ["DATABASE_URL"])
    schema = "test_" + uuid.uuid4().hex[:12]
    conn = connect()
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(f'create schema "{schema}"')
        cur.execute(f'set search_path to "{schema}"')
    conn.autocommit = False
    try:
        yield conn, schema
    finally:
        conn.rollback()
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(f'drop schema "{schema}" cascade')
        conn.close()
