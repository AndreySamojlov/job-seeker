import re
from pathlib import Path

from job_machine.db.connection import connect

MIGRATION_RE = re.compile(r"^(\d{4})_.+\.sql$")


def discover_migrations(directory):
    """Return [(number, name, path)] for files like 0001_name.sql, sorted by number."""
    directory = Path(directory)
    found = []
    for path in directory.glob("*.sql"):
        match = MIGRATION_RE.match(path.name)
        if match:
            found.append((int(match.group(1)), path.name, path))
    return sorted(found, key=lambda item: item[0])


def pending(all_migrations, applied_numbers):
    """Return migrations whose number is not in applied_numbers."""
    return [m for m in all_migrations if m[0] not in applied_numbers]


def ensure_tracking(conn):
    """Create the schema_migrations table if absent."""
    with conn.cursor() as cur:
        cur.execute(
            "create table if not exists schema_migrations ("
            "  number int primary key,"
            "  name text not null,"
            "  applied_at timestamptz not null default now()"
            ")"
        )
    conn.commit()


def applied_migrations(conn):
    """Return the set of applied migration numbers."""
    ensure_tracking(conn)
    with conn.cursor() as cur:
        cur.execute("select number from schema_migrations")
        return {row[0] for row in cur.fetchall()}


def apply_migration(conn, migration):
    """Run one migration's SQL and record it in schema_migrations."""
    number, name, path = migration
    sql = Path(path).read_text(encoding="utf-8")
    with conn.cursor() as cur:
        cur.execute(sql)
        cur.execute(
            "insert into schema_migrations (number, name) values (%s, %s)",
            (number, name),
        )
    conn.commit()


def main(migrations_dir="db/migrations"):
    """Apply all pending migrations; print a one-line summary per migration."""
    conn = connect()
    try:
        all_migs = discover_migrations(migrations_dir)
        todo = pending(all_migs, applied_migrations(conn))
        for migration in todo:
            apply_migration(conn, migration)
            print(f"applied {migration[0]:04d} {migration[1]}")
        if not todo:
            print("up to date")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
