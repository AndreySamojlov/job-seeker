import pytest

from job_machine.db import migrate
from job_machine.package import load_answer_vault, store


def _apply(conn):
    for m in migrate.pending(migrate.discover_migrations("db/migrations"),
                             migrate.applied_migrations(conn)):
        migrate.apply_migration(conn, m)


@pytest.mark.db
def test_load_file_upserts_answers(db_schema, tmp_path):
    conn, _ = db_schema
    _apply(conn)
    vault = tmp_path / "answers.md"
    vault.write_text(
        "| Field | Value | State | Rule |\n|---|---|---|---|\n"
        "| English | B2 | locked | no upgrade |\n"
        "| Salary | Not locked | blocked | ask |\n", encoding="utf-8")
    n = load_answer_vault.load_file(conn, str(vault), candidate_id="andrey-s")
    conn.commit()
    assert n == 2
    assert len(store.load_answers(conn, candidate_id="andrey-s")) == 2


def test_main_usage_without_path(capsys):
    assert load_answer_vault.main(["prog"]) == 2
