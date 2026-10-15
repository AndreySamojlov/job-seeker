import pytest

from job_machine.db import migrate
from job_machine.discovery import throttle


def _apply_migrations(conn):
    for m in migrate.pending(migrate.discover_migrations("db/migrations"),
                             migrate.applied_migrations(conn)):
        migrate.apply_migration(conn, m)


@pytest.mark.db
def test_should_skip_fetch_false_when_never_fetched(db_schema):
    conn, _ = db_schema
    _apply_migrations(conn)
    assert throttle.should_skip_fetch(conn, "remotive", min_interval_seconds=3600) is False


@pytest.mark.db
def test_record_fetch_then_skip_within_interval(db_schema):
    conn, _ = db_schema
    _apply_migrations(conn)
    throttle.record_fetch(conn, "remotive", "ok")
    assert throttle.should_skip_fetch(conn, "remotive", min_interval_seconds=3600) is True


@pytest.mark.db
def test_record_fetch_upserts_on_second_call(db_schema):
    conn, _ = db_schema
    _apply_migrations(conn)
    throttle.record_fetch(conn, "jobicy", "ok")
    throttle.record_fetch(conn, "jobicy", "ok")
    with conn.cursor() as cur:
        cur.execute("select count(*) from source_fetch_state where source_key = %s", ("jobicy",))
        assert cur.fetchone()[0] == 1


@pytest.mark.db
def test_should_skip_fetch_false_when_interval_is_zero(db_schema):
    conn, _ = db_schema
    _apply_migrations(conn)
    throttle.record_fetch(conn, "arbeitnow", "ok")
    assert throttle.should_skip_fetch(conn, "arbeitnow", min_interval_seconds=0) is False
