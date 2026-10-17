"""RWR migration allowlist and ledger gates."""
from pathlib import Path

import pytest

from job_machine.remote_readiness.migrations import (
    ALLOWED_MIGRATIONS,
    MigrationGateError,
    plan_from_ledger,
    validate_migration_files,
)
from job_machine.db.migrate import discover_migrations


ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = ROOT / "db" / "migrations"
BASE_ROWS = [(number, name) for number, name, _ in discover_migrations(MIGRATIONS) if number <= 38]


def test_unrelated_migration_file_is_never_included_in_rwr_plan(tmp_path):
    for name in ALLOWED_MIGRATIONS:
        (tmp_path / name).write_bytes((MIGRATIONS / name).read_bytes())
    (tmp_path / "0042_unrelated.sql").write_text("drop table vacancy;", encoding="utf-8")

    validated = validate_migration_files(tmp_path)

    assert [migration.number for migration in validated] == [39, 40, 41]


def test_changed_allowlisted_migration_fails_checksum_gate_before_planning(tmp_path):
    name = next(iter(ALLOWED_MIGRATIONS))
    (tmp_path / name).write_text("drop table vacancy;", encoding="utf-8")

    with pytest.raises(MigrationGateError, match="checksum"):
        validate_migration_files(tmp_path)


def test_board_reader_gets_only_the_completed_result_columns():
    sql = (MIGRATIONS / "0039_remote_work_readiness.sql").read_text(encoding="utf-8")

    sql = sql.lower()
    assert "if exists (select 1 from pg_roles where rolname = 'job_board_reader')" in sql
    assert "grant select (vacancy_id, status, value) on remote_work_readiness_job to job_board_reader" in sql
    assert "grant select on remote_work_readiness_job to job_board_reader" not in sql


def test_missing_base_ledger_entry_fails_before_any_rwr_migration_is_selected():
    rows = [row for row in BASE_ROWS if row[0] != 36]
    migrations = validate_migration_files(MIGRATIONS)

    with pytest.raises(MigrationGateError, match="ledger"):
        plan_from_ledger(rows, migrations)


def test_out_of_order_rwr_ledger_fails_closed():
    rows = BASE_ROWS + [
        (40, "0040_remote_work_readiness_intake.sql")
    ]
    migrations = validate_migration_files(MIGRATIONS)

    with pytest.raises(MigrationGateError, match="ledger"):
        plan_from_ledger(rows, migrations)


def test_correct_rwr_ledger_selects_only_missing_allowlisted_suffix():
    names = {int(name[:4]): name for name in ALLOWED_MIGRATIONS}
    rows = BASE_ROWS + [
        (39, names[39])
    ]
    migrations = validate_migration_files(MIGRATIONS)

    plan = plan_from_ledger(rows, migrations)

    assert [(migration.number, migration.name) for migration in plan] == [
        (40, names[40]), (41, names[41])
    ]
