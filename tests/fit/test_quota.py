"""Quota behavior against the guarded disposable recovery database only."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import importlib
import os
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg import sql
import pytest
from tests.conftest import apply_migrations

pytestmark = pytest.mark.db
NOW = datetime(2030, 1, 1, 23, 59, tzinfo=timezone.utc)


@pytest.fixture
def ledger(db_schema):
    conn, schema = db_schema
    name, port, directory = conn.execute("select current_database(),inet_server_port(),current_setting('data_directory')").fetchone()
    assert (name, port) == ('job_machine_recovery_test', 25439)
    assert Path(directory).resolve() == (Path(__file__).resolve().parents[2] / '.runtime/pg-recovery').resolve()
    apply_migrations(conn)
    conn.commit()
    @contextmanager
    def connect():
        with psycopg.connect(os.environ['DATABASE_URL']) as fresh:
            fresh.execute(sql.SQL('set search_path to {}').format(sql.Identifier(schema)))
            yield fresh
    return conn, connect


def reserve(conn, now=NOW, limit=1000):
    assert importlib.util.find_spec('job_machine.fit.quota'), 'quota reservation missing'
    from job_machine.fit.quota import reserve_request
    return reserve_request(conn, entity_type='vacancy', entity_id=uuid4(), now=now, daily_limit=limit)


def test_last_two_slots_boundary_and_restart_persistence(ledger):
    conn, connect = ledger
    conn.execute("insert into event(event_type,created_at) select 'fit.jev_request_reserved',%s from generate_series(1,998)", (NOW,))
    conn.commit()
    for _ in range(2):
        with connect() as fresh:
            assert reserve(fresh)
            fresh.commit()
    with connect() as fresh:
        assert not reserve(fresh)
        assert reserve(fresh, NOW + timedelta(minutes=1))
        fresh.commit()
    assert conn.execute("select count(*) from event where entity_id is not null and payload_json is not null").fetchone()[0] == 0
    assert conn.execute("select count(*) from event").fetchone()[0] == 1001


def test_concurrent_transactions_cannot_overshoot(ledger):
    conn, connect = ledger
    def attempt(_):
        with connect() as fresh:
            admitted = reserve(fresh, limit=1)
            fresh.commit()
            return admitted
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sum(pool.map(attempt, range(4))) == 1
    assert conn.execute('select count(*) from event').fetchone()[0] == 1


def test_timezone_conversion_and_rollback(ledger):
    conn, connect = ledger
    assert reserve(conn, limit=1)
    conn.rollback()
    with connect() as fresh:
        assert reserve(fresh, NOW.astimezone(timezone(timedelta(hours=3))), limit=1)
        fresh.commit()
    assert not reserve(conn, limit=1)


def test_non_read_committed_is_refused_before_reservation(ledger):
    conn, _ = ledger
    conn.execute('set transaction isolation level repeatable read')
    with pytest.raises(ValueError, match='read_committed_required'):
        reserve(conn)
    assert conn.execute('select count(*) from event').fetchone()[0] == 0
