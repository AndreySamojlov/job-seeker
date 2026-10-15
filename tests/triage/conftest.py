"""Общие фикстуры db-тестов триажа.

`migrated` — временная схема (db_schema) с уже применёнными миграциями. Заведена,
чтобы четырёхстрочный цикл `pending/apply_migration` не расползался копиями по
каждому новому db-тесту среза fit-2: модуль `job_machine.db.migrate` намеренно не
экспортирует пакетный хелпер, и без общей фикстуры его приходится повторять.
"""
import pytest

from job_machine.db import migrate


@pytest.fixture
def migrated(db_schema):
    """(conn, schema_name) с применёнными миграциями. Поверх conftest-фикстуры
    db_schema, которая создаёт и сносит временную схему."""
    conn, schema = db_schema
    for m in migrate.pending(migrate.discover_migrations("db/migrations"),
                             migrate.applied_migrations(conn)):
        migrate.apply_migration(conn, m)
    return conn, schema
