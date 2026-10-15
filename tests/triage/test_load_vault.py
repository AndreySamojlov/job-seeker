import pytest

from job_machine.db import migrate
from job_machine.triage import load_vault, store


def _apply(conn):
    for m in migrate.pending(migrate.discover_migrations("db/migrations"),
                             migrate.applied_migrations(conn)):
        migrate.apply_migration(conn, m)


SAMPLE = """## Claims

| ID | Claim | Status | Proof | Safe use |
|---|---|---|---|---|
| C-001 | a | verified | p | s |
"""


@pytest.mark.db
def test_load_text_upserts(db_schema, tmp_path):
    conn, _ = db_schema
    _apply(conn)
    f = tmp_path / "vault.md"
    f.write_text(SAMPLE, encoding="utf-8")
    n = load_vault.load_file(conn, str(f), "andrey-s")
    conn.commit()
    assert n == 1
    assert store.load_claims(conn, candidate_id="andrey-s")[0].claim_id == "C-001"
