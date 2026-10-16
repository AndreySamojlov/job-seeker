"""Integration tests run only through the guarded recovery database runner."""
from datetime import datetime, timezone, timedelta
from uuid import uuid4
from pathlib import Path
import pytest
from tests.conftest import apply_migrations

pytestmark = pytest.mark.db
NOW = datetime(2030, 1, 1, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def guarded_target(db_schema):
    conn, _ = db_schema
    database, port, directory = conn.execute("select current_database(),inet_server_port(),current_setting('data_directory')").fetchone()
    assert (database, port) == ('job_machine_recovery_test', 25439)
    assert Path(directory).resolve() == (Path(__file__).resolve().parents[2] / '.runtime/pg-recovery').resolve()


def test_fenced_text_reclaim_and_child_progress(db_schema):
    from job_machine.fit import preparation_store as store
    conn, _ = db_schema
    apply_migrations(conn)
    conn.execute('update candidate set active=false')
    conn.execute("insert into candidate(candidate_id,name,active) values ('prep-synthetic','Synthetic',true)")
    vacancy = uuid4()
    conn.execute("insert into vacancy(vacancy_id,title,vacancy_status) values (%s,'Synthetic','verified')", (vacancy,))
    conn.commit()
    first = store.claim_due(conn, now=NOW)
    conn.commit()
    assert first.vacancy_id == vacancy
    assert store.claim_due(conn, now=NOW) is None
    conn.commit()
    assert store.save_text(conn, first, 'Synthetic text', now=NOW)
    conn.commit()
    second = store.claim_due(conn, now=NOW + timedelta(seconds=61))
    conn.commit()
    assert second.job_text == 'Synthetic text'
    assert not store.prepare_child(conn, first, 'prep-synthetic', now=NOW + timedelta(seconds=61))
    assert store.prepare_child(conn, second, 'prep-synthetic', now=NOW + timedelta(seconds=61))
    conn.commit()
    assert store.finish(conn, second, now=NOW + timedelta(seconds=61)) == 'prepared'


def test_retry_block_recovery_and_immutable_text(db_schema):
    from job_machine.fit import preparation_store as store
    from job_machine.fit.models import FitError
    conn, _ = db_schema
    apply_migrations(conn)
    conn.execute('update candidate set active=false')
    conn.execute("insert into candidate(candidate_id,name,active) values ('prep-synthetic','Synthetic',true)")
    vacancy = uuid4()
    conn.execute("insert into vacancy(vacancy_id,title,vacancy_status) values (%s,'Synthetic','verified')", (vacancy,))
    conn.commit()
    job = store.claim_due(conn, now=NOW)
    conn.commit()
    assert store.save_text(conn, job, 'First synthetic text', now=NOW)
    assert store.save_text(conn, job, 'Replacement ignored', now=NOW)
    assert store.fail_child(conn, job, 'prep-synthetic', FitError('temporary', True), now=NOW)
    assert store.finish(conn, job, now=NOW) == 'retry_wait'
    conn.commit()
    assert store.claim_due(conn, now=NOW) is None
    conn.commit()
    later = NOW + timedelta(seconds=30)
    job = store.claim_due(conn, now=later)
    conn.commit()
    assert job.job_text == 'First synthetic text'
    assert store.fail_child(conn, job, 'prep-synthetic', FitError('https://secret.invalid'), now=later)
    assert store.finish(conn, job, now=later) == 'blocked'
    conn.commit()
    assert conn.execute('select last_error_code from fit_prepare_candidate').fetchone() == ('preparation_error',)
    assert store.rearm_blocked(conn, vacancy, candidate_id='prep-synthetic', now=later)
    conn.commit()
    assert store.claim_due(conn, now=later) is not None


def test_preparation_lease_can_be_renewed_after_ats_retry_budget(db_schema):
    from job_machine.fit import preparation_store as store
    conn, _ = db_schema
    apply_migrations(conn)
    conn.execute('update candidate set active=false')
    conn.execute("insert into candidate(candidate_id,name,active) values ('prep-synthetic','Synthetic',true)")
    vacancy = uuid4()
    conn.execute("insert into vacancy(vacancy_id,title,vacancy_status) values (%s,'Synthetic','verified')", (vacancy,))
    conn.commit()
    job = store.claim_due(conn, now=NOW, lease_seconds=360)
    conn.commit()
    after_ats_retry = NOW + timedelta(seconds=285)
    assert store.renew_lease(conn, job, now=after_ats_retry, lease_seconds=360)
    conn.commit()
    assert store.save_text(conn, job, 'Synthetic fetched excerpt', now=after_ats_retry)
    conn.commit()
