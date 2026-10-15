import pytest

from job_machine.db import migrate


def _apply(conn):
    for m in migrate.pending(migrate.discover_migrations("db/migrations"),
                             migrate.applied_migrations(conn)):
        migrate.apply_migration(conn, m)


@pytest.mark.db
def test_triage_result_has_fit_columns(db_schema):
    conn, _ = db_schema
    _apply(conn)
    with conn.cursor() as cur:
        cur.execute(
            "select column_name from information_schema.columns "
            "where table_name='triage_result'")
        cols = {r[0] for r in cur.fetchall()}
    assert {"fit_score", "fit_band", "fit_breakdown",
            "fit_score_version", "hard_requirements"} <= cols
