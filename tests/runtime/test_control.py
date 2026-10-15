import pytest

from tests.conftest import apply_migrations
from job_machine.runtime import control


@pytest.mark.db
def test_missing_row_reads_as_disabled(db_schema):
    conn, _schema = db_schema
    apply_migrations(conn)
    with conn.cursor() as cur:
        cur.execute("delete from runtime_control")
    conn.commit()
    assert control.is_submit_enabled(conn) is False


@pytest.mark.db
def test_migration_seeds_disabled(db_schema):
    conn, _schema = db_schema
    apply_migrations(conn)
    assert control.is_submit_enabled(conn) is False


@pytest.mark.db
def test_set_enabled_round_trip(db_schema):
    conn, _schema = db_schema
    apply_migrations(conn)
    assert control.set_submit_enabled(conn, True, actor="test") is True
    conn.commit()
    assert control.is_submit_enabled(conn) is True


@pytest.mark.db
def test_conflicting_locks_rejected(db_schema):
    conn, _schema = db_schema
    apply_migrations(conn)
    with pytest.raises(ValueError, match="conflicting_runtime_control_locks"):
        control.is_submit_enabled(conn, for_update=True, for_share=True)
