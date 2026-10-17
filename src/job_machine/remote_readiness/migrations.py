"""Fail-closed migration runner for the RWR schema migrations."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
import sys

from job_machine.db.connection import connect
from psycopg.pq import TransactionStatus


MIGRATIONS_DIR = Path(__file__).resolve().parents[3] / "db" / "migrations"
MIGRATION_RE = re.compile(r"^(\d{4})_.+\.sql$")
ALLOWED_MIGRATIONS = {
    "0039_remote_work_readiness.sql": "add432b8a3cdb36fd18bdb91f87c1d5113e912044b1c2229c19b5ce1d0f221da",
    "0040_remote_work_readiness_intake.sql": "6a27830fbd153c0652dd856cd727d3539d7a7017f0641bc00fdfbd2bf61cc77f",
    "0041_remote_work_readiness_control.sql": "6bf0f86807b46e5f2de674ac2e512c80a5ba2ef8901ae70ab5c38f62dc8c9a8a",
    "0042_remote_work_readiness_mark_stale.sql": "a034f2edfef1445ba6aae575268fd7c0ffd4ade5011e743414fe0ec5b576cad6",
}
ALLOWED_NAMES = {int(name[:4]): name for name in ALLOWED_MIGRATIONS}
REQUIRED_BASE_HEAD = 38
REQUIRED_BASE_HEAD_NAME = "0038_vacancy_fit_preparation.sql"
ADVISORY_LOCK_NAMESPACE = 741990041


class MigrationGateError(RuntimeError):
    """A migration precondition failed; no pending migration was applied."""


@dataclass(frozen=True)
class Migration:
    number: int
    name: str
    path: Path
    sha256: str


@dataclass(frozen=True)
class Preflight:
    target: str
    applied: tuple[int, ...]
    pending: tuple[Migration, ...]


def validate_migration_files(directory: Path = MIGRATIONS_DIR) -> tuple[Migration, ...]:
    """Verify exact filenames and pinned hashes; ignore every unlisted SQL file."""
    directory = Path(directory)
    found: list[Migration] = []
    for name, expected_hash in ALLOWED_MIGRATIONS.items():
        path = directory / name
        if not path.is_file():
            raise MigrationGateError(f"allowlisted migration is missing: {name}")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != expected_hash:
            raise MigrationGateError(f"checksum mismatch for {name}")
        found.append(Migration(int(name[:4]), name, path, digest))

    for path in directory.glob("*.sql"):
        match = MIGRATION_RE.match(path.name)
        if match and int(match.group(1)) in ALLOWED_NAMES and path.name != ALLOWED_NAMES[int(match.group(1))]:
            raise MigrationGateError(f"unexpected filename for allowlisted migration {match.group(1)}")
    return tuple(found)


def _known_migration_names(directory: Path = MIGRATIONS_DIR) -> dict[int, str]:
    names: dict[int, str] = {}
    for path in Path(directory).glob("*.sql"):
        match = MIGRATION_RE.match(path.name)
        if match:
            number = int(match.group(1))
            if number in names:
                raise MigrationGateError(f"duplicate migration number in source: {number:04d}")
            names[number] = path.name
    return names


def plan_from_ledger(rows, migrations: tuple[Migration, ...], *, source_directory: Path = MIGRATIONS_DIR) -> tuple[Migration, ...]:
    """Validate contiguous history and return only the unapplied RWR suffix."""
    ledger = tuple((int(number), str(name)) for number, name in rows)
    numbers = tuple(number for number, _ in ledger)
    if numbers != tuple(sorted(set(numbers))):
        raise MigrationGateError("migration ledger is duplicated or out of order")
    head = numbers[-1] if numbers else 0
    if head < REQUIRED_BASE_HEAD or head > max(ALLOWED_NAMES):
        raise MigrationGateError("migration ledger head is outside the supported RWR range")
    if numbers != tuple(range(1, head + 1)):
        raise MigrationGateError("migration ledger has a missing or out-of-order entry")

    known_names = _known_migration_names(source_directory)
    for number, name in ledger:
        expected = ALLOWED_NAMES.get(number) or known_names.get(number)
        if expected is None or name != expected:
            raise MigrationGateError(f"migration ledger name mismatch at {number:04d}")
    if known_names.get(REQUIRED_BASE_HEAD) != REQUIRED_BASE_HEAD_NAME:
        raise MigrationGateError("required migration 0038 source is unavailable")

    applied_rwr = tuple(number for number in numbers if number >= REQUIRED_BASE_HEAD + 1)
    if applied_rwr != tuple(range(REQUIRED_BASE_HEAD + 1, head + 1)):
        raise MigrationGateError("RWR migrations are not an ordered prefix")
    available = {migration.number: migration for migration in migrations}
    return tuple(available[number] for number in ALLOWED_NAMES if number > head)


def _read_ledger(conn):
    exists = conn.execute(
        "select to_regclass(format('%I.schema_migrations', current_schema())) is not null"
    ).fetchone()[0]
    if not exists:
        raise MigrationGateError("schema_migrations table is missing")
    return conn.execute("select number, name from schema_migrations order by number").fetchall()


def preflight(conn, directory: Path = MIGRATIONS_DIR) -> Preflight:
    """Read and validate the ledger in a transaction enforced read-only by PostgreSQL."""
    if conn.info.transaction_status != TransactionStatus.IDLE:
        raise MigrationGateError("connection must be idle before preflight")
    migrations = validate_migration_files(directory)
    try:
        with conn.transaction():
            conn.execute("set transaction read only")
            database, address, port = conn.execute(
                "select current_database(), inet_server_addr()::text, inet_server_port()"
            ).fetchone()
            if not address or not port:
                raise MigrationGateError("target has no TCP server identity")
            rows = _read_ledger(conn)
            plan = plan_from_ledger(rows, migrations, source_directory=MIGRATIONS_DIR)
    except MigrationGateError:
        raise
    except Exception as exc:
        raise MigrationGateError("read-only migration preflight failed") from exc
    return Preflight(f"{address}:{port}/{database}", tuple(int(row[0]) for row in rows), plan)


def apply_pending(conn, *, expected_target: str, directory: Path = MIGRATIONS_DIR) -> tuple[int, ...]:
    """Apply only allowlisted missing RWR migrations, each atomically after rechecking."""
    initial = preflight(conn, directory)
    if initial.target != expected_target:
        raise MigrationGateError("target identity does not match expected target")
    applied: list[int] = []
    for migration in initial.pending:
        try:
            with conn.transaction():
                conn.execute("select pg_advisory_xact_lock(%s, %s)", (ADVISORY_LOCK_NAMESPACE, migration.number))
                rows = _read_ledger(conn)
                current = plan_from_ledger(rows, validate_migration_files(directory), source_directory=MIGRATIONS_DIR)
                if not current or current[0].number != migration.number:
                    raise MigrationGateError("migration ledger changed after preflight")
                source = migration.path.read_bytes()
                if hashlib.sha256(source).hexdigest() != migration.sha256:
                    raise MigrationGateError(f"checksum mismatch for {migration.name}")
                conn.execute(source.decode("utf-8"))
                conn.execute(
                    "insert into schema_migrations(number, name) values (%s, %s)",
                    (migration.number, migration.name),
                )
            applied.append(migration.number)
        except MigrationGateError:
            raise
        except Exception as exc:
            raise MigrationGateError(f"applying {migration.name} failed; later migrations were not attempted") from exc
    return tuple(applied)


def _format(report: Preflight) -> str:
    pending = ", ".join(f"{item.number:04d}" for item in report.pending) or "none"
    head = report.applied[-1] if report.applied else 0
    return f"target={report.target} ledger_head={head:04d} pending={pending}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("preflight", help="read-only RWR migration preflight")
    apply_parser = subparsers.add_parser("apply", help="apply only pinned RWR migrations 0039-0042")
    apply_parser.add_argument("--expect-target", required=True, help="exact target string from preflight: address:port/database")
    args = parser.parse_args(argv)

    conn = connect()
    try:
        report = preflight(conn)
        print(_format(report))
        if args.command == "preflight":
            return 0
        if report.target != args.expect_target:
            raise MigrationGateError("target identity does not match --expect-target")
        applied = apply_pending(conn, expected_target=args.expect_target)
        print("applied=" + (",".join(f"{number:04d}" for number in applied) or "none"))
        return 0
    except MigrationGateError as exc:
        print(f"migration gate refused: {exc}", file=sys.stderr)
        return 2
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
