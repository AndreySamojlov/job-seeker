import pytest

from job_machine.db import migrate


def _apply(conn):
    for m in migrate.pending(migrate.discover_migrations("db/migrations"),
                             migrate.applied_migrations(conn)):
        migrate.apply_migration(conn, m)


@pytest.mark.db
def test_search_profile_table_exists_and_seeds_default(db_schema):
    conn, _ = db_schema
    _apply(conn)
    with conn.cursor() as cur:
        cur.execute("select candidate_id, work_mode from search_profile "
                    "where candidate_id='andrey-s'")
        row = cur.fetchone()
    assert row is not None
    assert row[0] == "andrey-s"
