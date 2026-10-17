"""RWR-only migration rehearsal; run only through scripts/check_schema.py db."""
from pathlib import Path

import pytest

from job_machine.db.migrate import discover_migrations
from job_machine.remote_readiness.migrations import MigrationGateError, apply_pending, preflight

pytestmark = pytest.mark.db
ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR = ROOT / "db" / "migrations"


def seed_base_ledger(conn, *, omit=()):
    migrations = discover_migrations(MIGRATIONS_DIR)
    conn.execute("create table schema_migrations(number integer primary key, name text not null)")
    conn.execute(
        "create table vacancy(vacancy_id uuid primary key, work_mode text, vacancy_status text, verified_at timestamptz)"
    )
    with conn.cursor() as cursor:
        cursor.executemany(
            "insert into schema_migrations(number,name) values (%s,%s)",
            [(number, name) for number, name, _ in migrations if number <= 38 and number not in omit],
        )
    conn.commit()


def rwr_tables(conn):
    return {
        row[0]
        for row in conn.execute(
            "select table_name from information_schema.tables where table_schema=current_schema()"
        ).fetchall()
        if row[0].startswith("remote_work_readiness_")
    }


def test_preflight_is_read_only_then_apply_is_allowlisted_repeatable(db_schema):
    conn, _ = db_schema
    seed_base_ledger(conn)
    before = conn.execute("select number,name from schema_migrations order by number").fetchall()
    assert rwr_tables(conn) == set()
    conn.commit()

    report = preflight(conn)

    assert [migration.number for migration in report.pending] == [39, 40, 41, 42]
    assert conn.execute("select number,name from schema_migrations order by number").fetchall() == before
    assert rwr_tables(conn) == set()
    conn.commit()

    assert apply_pending(conn, expected_target=report.target) == (39, 40, 41, 42)
    assert rwr_tables(conn) == {
        "remote_work_readiness_job",
        "remote_work_readiness_intake",
        "remote_work_readiness_control",
    }
    conn.commit()
    report = preflight(conn)
    assert apply_pending(conn, expected_target=report.target) == ()
    assert conn.execute("select number from schema_migrations order by number desc limit 4").fetchall() == [
        (42,), (41,), (40,), (39,)
    ]


def test_preflight_refuses_missing_base_ledger_entry_before_ddl(db_schema):
    conn, _ = db_schema
    seed_base_ledger(conn, omit=(36,))

    with pytest.raises(MigrationGateError, match="ledger"):
        apply_pending(conn, expected_target="127.0.0.1:25439/job_machine_recovery_test")

    assert rwr_tables(conn) == set()
    assert conn.execute("select max(number) from schema_migrations").fetchone() == (38,)


def test_preflight_refuses_changed_rwr_ledger_name_before_ddl(db_schema):
    conn, _ = db_schema
    seed_base_ledger(conn)
    conn.execute("insert into schema_migrations(number,name) values (39,'0039_changed.sql')")
    conn.commit()

    with pytest.raises(MigrationGateError, match="ledger"):
        apply_pending(conn, expected_target="127.0.0.1:25439/job_machine_recovery_test")

    assert rwr_tables(conn) == set()


def test_preflight_refuses_out_of_order_rwr_ledger_before_ddl(db_schema):
    conn, _ = db_schema
    seed_base_ledger(conn)
    conn.execute("insert into schema_migrations(number,name) values (40,'0040_remote_work_readiness_intake.sql')")
    conn.commit()

    with pytest.raises(MigrationGateError, match="ledger"):
        apply_pending(conn, expected_target="127.0.0.1:25439/job_machine_recovery_test")

    assert rwr_tables(conn) == set()
