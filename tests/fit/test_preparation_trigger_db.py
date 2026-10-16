"""Verified events persist an atomic synthetic recipient snapshot."""
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

import psycopg
from psycopg import sql
import pytest

from tests.conftest import apply_migrations

pytestmark = pytest.mark.db


@pytest.fixture
def preparation_db(db_schema):
    conn, schema = db_schema
    apply_migrations(conn)
    conn.execute('update candidate set active=false')
    conn.commit()
    return conn, schema


def add_vacancy(conn, status='verified'):
    vacancy = uuid4()
    conn.execute("insert into vacancy(vacancy_id,title,vacancy_status) values (%s,'Synthetic',%s)", (vacancy,status))
    return vacancy


@pytest.mark.parametrize('initial', ['verified', 'discovered'])
def test_first_verified_event_snapshots_active_candidates_once(preparation_db, initial):
    conn, _ = preparation_db
    conn.execute("insert into candidate(candidate_id,name,active) values ('active','Synthetic',true),('inactive','Synthetic',false)")
    vacancy = add_vacancy(conn, initial)
    if initial == 'discovered':
        assert conn.execute('select count(*) from fit_prepare').fetchone() == (0,)
        conn.execute("update vacancy set vacancy_status='verified' where vacancy_id=%s", (vacancy,))
    assert conn.execute('select candidate_id from fit_prepare_candidate').fetchall() == [('active',)]
    conn.execute("update candidate set active=false where candidate_id='active'")
    conn.execute("update candidate set active=true where candidate_id='inactive'")
    conn.execute("update vacancy set title='Changed',vacancy_status='discovered' where vacancy_id=%s", (vacancy,))
    conn.execute("update vacancy set vacancy_status='verified' where vacancy_id=%s", (vacancy,))
    assert conn.execute('select count(*) from fit_prepare').fetchone() == (1,)
    assert conn.execute('select candidate_id from fit_prepare_candidate').fetchall() == [('active',)]


def test_empty_snapshot_is_completed_and_late_candidate_is_not_added(preparation_db):
    conn, _ = preparation_db
    vacancy = add_vacancy(conn)
    assert conn.execute('select status,completed_at is not null from fit_prepare').fetchone() == ('completed', True)
    conn.execute("insert into candidate(candidate_id,name) values ('late','Synthetic')")
    conn.execute("update vacancy set title='Changed' where vacancy_id=%s", (vacancy,))
    assert conn.execute('select count(*) from fit_prepare_candidate').fetchone() == (0,)


@pytest.mark.parametrize('mutation', ['insert', 'activate', 'deactivate'])
def test_candidate_change_before_verify_serializes_snapshot(preparation_db, mutation):
    conn, schema = preparation_db
    if mutation != 'insert':
        conn.execute("insert into candidate(candidate_id,name,active) values ('racer','Synthetic',%s)", (mutation == 'deactivate',))
        conn.commit()
    started = Event()
    def verify():
        with psycopg.connect(os.environ['DATABASE_URL']) as other:
            other.execute(sql.SQL('set search_path to {}').format(sql.Identifier(schema)))
            started.set()
            add_vacancy(other)
    if mutation == 'insert':
        conn.execute("insert into candidate(candidate_id,name) values ('racer','Synthetic')")
    else:
        conn.execute("update candidate set active=%s where candidate_id='racer'", (mutation == 'activate',))
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(verify)
        assert started.wait(5)
        # The writer owns the transaction lock until commit; verification cannot finish.
        with pytest.raises(TimeoutError):
            future.result(timeout=0.2)
        conn.commit()
        future.result(timeout=5)
    expected = [] if mutation == 'deactivate' else [('racer',)]
    assert conn.execute('select candidate_id from fit_prepare_candidate').fetchall() == expected


def test_migration_does_not_backfill_existing_verified_rows(db_schema):
    from job_machine.db import migrate
    conn, _ = db_schema
    migrate.ensure_tracking(conn)
    for migration in migrate.discover_migrations('db/migrations'):
        if migration[0] < 38:
            migrate.apply_migration(conn, migration)
    add_vacancy(conn)
    apply_migrations(conn)
    assert conn.execute('select count(*) from fit_prepare').fetchone() == (0,)


@pytest.mark.parametrize('statement', [
    "delete from fit_prepare_candidate",
    "update fit_prepare_candidate set candidate_id='other'",
    "delete from fit_prepare",
])
def test_recipient_assignment_cannot_be_replaced(preparation_db, statement):
    conn, _ = preparation_db
    conn.execute("insert into candidate(candidate_id,name) values ('first','Synthetic'),('other','Synthetic')")
    add_vacancy(conn)
    with pytest.raises(psycopg.Error), conn.transaction():
        conn.execute(statement)


def test_verify_before_activation_keeps_empty_snapshot(preparation_db):
    conn, schema = preparation_db
    conn.execute("insert into candidate(candidate_id,name,active) values ('late','Synthetic',false)")
    conn.commit()
    add_vacancy(conn)
    started = Event()
    def activate():
        with psycopg.connect(os.environ['DATABASE_URL']) as other:
            other.execute(sql.SQL('set search_path to {}').format(sql.Identifier(schema)))
            started.set()
            other.execute("update candidate set active=true where candidate_id='late'")
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(activate)
        assert started.wait(5)
        with pytest.raises(TimeoutError):
            future.result(timeout=0.2)
        conn.commit()
        future.result(timeout=5)
    assert conn.execute('select status from fit_prepare').fetchone() == ('completed',)
    assert conn.execute('select count(*) from fit_prepare_candidate').fetchone() == (0,)
