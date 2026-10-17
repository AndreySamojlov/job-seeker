"""Assembled lifecycle tests: guarded recovery PostgreSQL and fake HTTP only."""
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
from uuid import uuid4

import httpx
import psycopg
from psycopg import sql
import pytest

from tests.conftest import apply_migrations
from job_machine.fit import store, worker
from job_machine.fit.models import FitFact, FitInput

pytestmark = pytest.mark.db


@pytest.fixture
def lifecycle(db_schema):
    conn, schema = db_schema
    database, port, directory = conn.execute(
        "select current_database(),inet_server_port(),current_setting('data_directory')"
    ).fetchone()
    assert (database, port) == ("job_machine_recovery_test", 25439)
    assert Path(directory).resolve() == (Path(__file__).resolve().parents[2] / ".runtime/pg-recovery").resolve()
    apply_migrations(conn)
    vacancy = uuid4()
    conn.execute("insert into candidate(candidate_id,name) values ('worker-synthetic','Synthetic')")
    conn.execute("insert into vacancy(vacancy_id,title) values (%s,'Synthetic')", (vacancy,))
    value = FitInput("worker-synthetic", vacancy, "Synthetic Python role", (
        FitFact("python", "Synthetic Python experience", "verified", "synthetic"),))
    assert store.create_job(conn, value)
    conn.commit()
    @contextmanager
    def connect():
        with psycopg.connect(os.environ["DATABASE_URL"]) as fresh:
            fresh.execute(sql.SQL("set search_path to {}").format(sql.Identifier(schema)))
            yield fresh
    return conn, value, connect


def response():
    return httpx.Response(200, json={"model": "jev-1.13.0", "answers": {
        "fit_score": {"type": "score", "score": 3},
        "mandatory_requirement": {"type": "choice", "choice": "unknown"}}})


def test_assembled_success_inactive_and_completed_not_reopened(lifecycle):
    conn, _, connect = lifecycle
    now = datetime(2030, 1, 1, tzinfo=timezone.utc)
    conn.execute("update candidate set active=false where candidate_id='worker-synthetic'")
    conn.commit()
    requests = []
    def send(request):
        requests.append(request.content)
        # Claim is committed before network; a second connection sees processing.
        with connect() as observer:
            assert observer.execute("select status from fit_job").fetchone()[0] == "processing"
        return response()
    with httpx.Client(transport=httpx.MockTransport(send)) as client:
        assert worker.run_once(connect, client=client, api_key="synthetic", clock=lambda: now) == "completed"
        assert worker.run_once(connect, client=client, api_key="synthetic", clock=lambda: now) == "idle"
    assert len(requests) == 1
    assert conn.execute("select status,score,attempts from fit_job").fetchone() == ("completed", 75, 1)
    assert not store.rearm_blocked(conn, "worker-synthetic", lifecycle[1].vacancy_id, now=now)


def test_assembled_retry_keeps_snapshot_and_respects_delay(lifecycle):
    conn, value, connect = lifecycle
    now = datetime(2030, 1, 1, tzinfo=timezone.utc)
    requests = []
    def send(request):
        requests.append(request.content)
        if len(requests) == 1:
            return httpx.Response(429, headers={"Retry-After": "90"})
        return response()
    with httpx.Client(transport=httpx.MockTransport(send)) as client:
        assert worker.run_once(connect, client=client, api_key="synthetic", clock=lambda: now) == "retry_wait"
        assert conn.execute("select next_attempt_at,score from fit_job").fetchone() == (now + timedelta(seconds=90), None)
        assert not store.create_job(conn, replace(value, job_text="Changed external vacancy", facts=()))
        conn.commit()
        assert worker.run_once(connect, client=client, api_key="synthetic", clock=lambda: now + timedelta(seconds=89)) == "idle"
        assert worker.run_once(connect, client=client, api_key="synthetic", clock=lambda: now + timedelta(seconds=90)) == "completed"
    assert requests[0] == requests[1]
    assert conn.execute("select score,attempts from fit_job").fetchone() == (75, 2)


def test_assembled_crash_then_expired_response_then_recovery(lifecycle, monkeypatch):
    conn, _, connect = lifecycle
    now = datetime(2030, 1, 1, tzinfo=timezone.utc)
    requests = []
    def send(request):
        requests.append(request.content)
        return response()
    original = store.complete
    def crash(*args, **kwargs): raise RuntimeError("synthetic crash")
    with httpx.Client(transport=httpx.MockTransport(send)) as client:
        monkeypatch.setattr(store, "complete", crash)
        with pytest.raises(RuntimeError):
            worker.run_once(connect, client=client, api_key="synthetic", clock=lambda: now)
        assert conn.execute("select status,score from fit_job").fetchone() == ("processing", None)
        conn.rollback()
        monkeypatch.setattr(store, "complete", original)
        # claim, post-lock reservation, post-commit day check, then expired response
        times = iter([now + timedelta(seconds=60), now + timedelta(seconds=60),
                      now + timedelta(seconds=60), now + timedelta(seconds=121)])
        assert worker.run_once(connect, client=client, api_key="synthetic", clock=lambda: next(times)) == "lease_lost"
        assert worker.run_once(connect, client=client, api_key="synthetic", clock=lambda: now + timedelta(seconds=122)) == "completed"
    assert len(requests) == 3
    assert requests[0] == requests[1] == requests[2]
    assert conn.execute("select score,attempts from fit_job").fetchone() == (75, 3)


@pytest.mark.parametrize("key,http_status,error", [("", 200, "missing_api_key"), ("synthetic", 401, "http_401")])
def test_assembled_blocked_requires_explicit_rearm(lifecycle, key, http_status, error):
    conn, value, connect = lifecycle
    now = datetime(2030, 1, 1, tzinfo=timezone.utc)
    requests = []
    def send(request):
        requests.append(request.content)
        return httpx.Response(http_status)
    with httpx.Client(transport=httpx.MockTransport(send)) as client:
        assert worker.run_once(connect, client=client, api_key=key, clock=lambda: now) == "blocked"
        assert worker.run_once(connect, client=client, api_key=key, clock=lambda: now + timedelta(days=1)) == "idle"
    assert len(requests) == int(bool(key))
    assert conn.execute("select status,score,last_error_code,attempts from fit_job").fetchone() == ("blocked", None, error, 1)
    before = conn.execute("select payload_hash from fit_job").fetchone()[0]
    assert store.rearm_blocked(conn, value.candidate_id, value.vacancy_id, now=now)
    conn.commit()
    assert conn.execute("select status,payload_hash,attempts from fit_job").fetchone() == ("retry_wait", before, 1)


def test_quota_deferral_is_fenced_and_keeps_snapshot(lifecycle):
    conn, _, connect = lifecycle
    now = datetime(2030, 1, 1, tzinfo=timezone.utc)
    def forbidden(request): pytest.fail('HTTP called after quota exhaustion')
    with httpx.Client(transport=httpx.MockTransport(forbidden)) as client:
        assert worker.run_once(connect, client=client, api_key='synthetic', clock=lambda: now,
            reserve_request=lambda *a, **kw: False) == 'quota_exhausted'
    row = conn.execute('select status,next_attempt_at,score,lease_token,last_error_code,payload_hash from fit_job').fetchone()
    assert row[:5] == ('retry_wait', now + timedelta(days=1), None, None, 'quota_exhausted')
    conn.rollback()
    with connect() as fresh:
        job = store.claim_due(fresh, now=now + timedelta(days=1))
        fresh.commit()
    assert not store.defer_for_quota(conn, job, retry_at=now + timedelta(days=2), now=now + timedelta(days=1, seconds=61))
    assert conn.execute('select payload_hash from fit_job').fetchone()[0] == row[5]


def test_worker_reservation_is_durable_before_network_and_after_crash(lifecycle, monkeypatch):
    conn, _, connect = lifecycle
    now = datetime(2030, 1, 1, tzinfo=timezone.utc)
    def send(request):
        with connect() as observer:
            assert observer.execute("select count(*) from event where event_type='fit.jev_request_reserved'").fetchone()[0] == 1
        return response()
    def crash(*a, **kw): raise RuntimeError('synthetic crash')
    monkeypatch.setattr(store, 'complete', crash)
    with httpx.Client(transport=httpx.MockTransport(send)) as client:
        with pytest.raises(RuntimeError):
            worker.run_once(connect, client=client, api_key='synthetic', clock=lambda: now)
    assert conn.execute("select count(*) from event where event_type='fit.jev_request_reserved'").fetchone()[0] == 1


def test_greenhouse_claim_filters_preparation_and_fit(lifecycle):
    from job_machine.fit import preparation_store
    conn, value, connect = lifecycle
    now = datetime(2030, 1, 1, tzinfo=timezone.utc)
    conn.execute("update vacancy set ats_family='lever' where vacancy_id=%s", (value.vacancy_id,))
    conn.execute("insert into fit_prepare(vacancy_id) values (%s)", (value.vacancy_id,))
    conn.commit()
    assert preparation_store.claim_due(conn, now=now, ats_family='greenhouse') is None
    conn.commit()
    assert store.claim_due(conn, now=now, ats_family='greenhouse') is None
    conn.commit()
    conn.execute("update vacancy set ats_family='greenhouse' where vacancy_id=%s", (value.vacancy_id,))
    conn.commit()
    assert preparation_store.claim_due(conn, now=now, ats_family='greenhouse').vacancy_id == value.vacancy_id
    conn.commit()
    assert store.claim_due(conn, now=now, ats_family='greenhouse').vacancy_id == value.vacancy_id
