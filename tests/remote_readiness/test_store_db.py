"""Synthetic snapshots; run only through the guarded recovery runner."""
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg import sql
import pytest

from tests.conftest import apply_migrations

pytestmark = pytest.mark.db
NOW = datetime(2030, 1, 1, tzinfo=timezone.utc)
PAYLOAD = {"model": "jev-1.13.0", "state": {"rubric_version": "rwr-1", "job_text": "Synthetic vacancy"}, "questions": {"noul": {"type": "noul"}}}


@dataclass(frozen=True)
class Answer:
    value: float
    model: str = "jev-1.13.0"
    rubric_version: str = "rwr-1"


@dataclass(frozen=True)
class Error:
    code: str = "timeout"
    retryable: bool = True
    retry_after_seconds: float | None = None


@pytest.fixture
def readiness_db(db_schema):
    conn, schema = db_schema
    database, port, directory = conn.execute(
        "select current_database(),inet_server_port(),current_setting('data_directory')"
    ).fetchone()
    assert (database, port) == ("job_machine_recovery_test", 25439)
    assert Path(directory).resolve() == (Path(__file__).resolve().parents[2] / ".runtime/pg-recovery").resolve()
    apply_migrations(conn)
    vacancy = uuid4()
    conn.execute("insert into vacancy(vacancy_id,title) values (%s,'Synthetic QA')", (vacancy,))
    conn.commit()
    from job_machine.remote_readiness.store import ReadinessInput
    return conn, schema, ReadinessInput(vacancy, "Synthetic vacancy", "unknown")


def queued(readiness_db):
    from job_machine.remote_readiness import store
    conn, schema, value = readiness_db
    assert store.create_job(conn, value, payload=PAYLOAD)
    conn.commit()
    return conn, schema, value


def test_duplicate_preserves_first_snapshot(readiness_db):
    from job_machine.remote_readiness import store
    conn, _, value = queued(readiness_db)
    before = conn.execute("select payload,payload_hash,value from remote_work_readiness_job").fetchone()
    assert before[2] is None
    assert not store.create_job(conn, replace(value, job_text="Changed"), payload={**PAYLOAD, "questions": {}})
    assert conn.execute("select payload,payload_hash,value from remote_work_readiness_job").fetchone() == before


def test_snapshot_keeps_canonical_provider_payload_and_hash(readiness_db):
    import hashlib
    import json
    from job_machine.remote_readiness import store
    conn, _, value = readiness_db
    payload = {"state": {"rubric_version": "rwr-1", "job_text": "Synthetic"},
               "model": "jev-1.13.0", "questions": {"noul": {"type": "noul"}}}
    original = json.loads(json.dumps(payload))
    digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                      separators=(",", ":")).encode()).hexdigest()
    assert store.create_job(conn, value, payload=payload)
    payload["state"]["job_text"] = "Changed"
    assert conn.execute("select payload,payload_hash,model,rubric_version from remote_work_readiness_job").fetchone() == (
        original, digest, "jev-1.13.0", "rwr-1")
    conn.rollback()
    assert conn.execute("select count(*) from remote_work_readiness_job").fetchone() == (0,)


@pytest.mark.parametrize("mode,expected", [("onsite", False), ("remote", True), ("hybrid", True), ("unknown", True)])
def test_work_mode_eligibility(readiness_db, mode, expected):
    from job_machine.remote_readiness import store
    conn, _, value = readiness_db
    assert store.create_job(conn, replace(value, work_mode=mode), payload=PAYLOAD) is expected
    assert conn.execute("select count(*) from remote_work_readiness_job").fetchone()[0] == int(expected)


@pytest.mark.parametrize("value", [0.0, 1.0, 0.12345678901234568])
def test_complete_preserves_fraction_and_freezes_row(readiness_db, value):
    from job_machine.remote_readiness import store
    conn, _, _ = queued(readiness_db)
    job = store.claim_due(conn, now=NOW)
    assert store.complete(conn, job, Answer(value), now=NOW)
    conn.commit()
    assert conn.execute("select status,value from remote_work_readiness_job").fetchone() == ("completed", value)
    for statement in ("update remote_work_readiness_job set value=0.5", "delete from remote_work_readiness_job"):
        with pytest.raises(psycopg.errors.CheckViolation), conn.transaction():
            conn.execute(statement)


def test_expired_and_superseded_leases_are_fenced(readiness_db):
    from job_machine.remote_readiness import store
    conn, _, _ = queued(readiness_db)
    old = store.claim_due(conn, now=NOW, lease_seconds=5)
    conn.commit()
    later = NOW + timedelta(seconds=5)
    assert not store.complete(conn, old, Answer(0.4), now=later)
    assert not store.fail(conn, old, Error(), now=later)
    new = store.claim_due(conn, now=later)
    conn.commit()
    assert new.lease_token != old.lease_token and new.attempts == 2
    assert (new.payload_hash, new.payload) == (old.payload_hash, old.payload)
    assert not store.complete(conn, old, Answer(0.4), now=later)
    assert not store.fail(conn, old, Error(), now=later)
    assert store.complete(conn, new, Answer(0.4), now=later)


def test_concurrent_claim_skips_locked_and_rollback_releases(readiness_db):
    from job_machine.remote_readiness import store
    conn, schema, _ = queued(readiness_db)
    with psycopg.connect(os.environ["DATABASE_URL"]) as other:
        other.execute(sql.SQL("set search_path to {}").format(sql.Identifier(schema)))
        assert store.claim_due(conn, now=NOW) is not None
        assert store.claim_due(other, now=NOW) is None
        conn.rollback()
        assert store.claim_due(other, now=NOW) is not None


def test_retry_and_rearm_preserve_snapshot(readiness_db):
    from job_machine.remote_readiness import store
    conn, _, value = queued(readiness_db)
    job = store.claim_due(conn, now=NOW)
    assert store.fail(conn, job, Error(retry_after_seconds=90), now=NOW)
    conn.commit()
    assert store.claim_due(conn, now=NOW + timedelta(seconds=89)) is None
    job2 = store.claim_due(conn, now=NOW + timedelta(seconds=90))
    assert job2.payload == job.payload and job2.payload_hash == job.payload_hash
    assert store.fail(conn, job2, Error("invalid_response", False), now=NOW + timedelta(seconds=90))
    conn.commit()
    assert conn.execute("select status,value from remote_work_readiness_job").fetchone() == ("blocked", None)
    assert store.claim_due(conn, now=NOW + timedelta(days=1)) is None
    assert store.rearm_blocked(conn, value.vacancy_id, now=NOW)
    job3 = store.claim_due(conn, now=NOW)
    assert job3.payload_hash == job.payload_hash and job3.attempts == 1
    assert store.complete(conn, job3, Answer(0.9), now=NOW)
    conn.commit()
    assert not store.rearm_blocked(conn, value.vacancy_id, now=NOW)


def test_configured_attempt_limit_blocks_jev_retry_at_limit(readiness_db):
    from job_machine.remote_readiness import store
    conn, _, _ = queued(readiness_db)
    first = store.claim_due(conn, now=NOW, max_attempts=2)
    assert store.fail(conn, first, Error(), now=NOW, max_attempts=2)
    conn.commit()
    second = store.claim_due(conn, now=NOW + timedelta(seconds=30), max_attempts=2)
    assert second.attempts == 2
    assert store.fail(conn, second, Error(), now=NOW + timedelta(seconds=30), max_attempts=2)
    conn.commit()
    assert conn.execute("select status from remote_work_readiness_job").fetchone() == ("blocked",)
    assert store.claim_due(conn, now=NOW + timedelta(days=1), max_attempts=2) is None


def test_crashed_final_jev_lease_expires_to_blocked(readiness_db):
    from job_machine.remote_readiness import store
    conn, _, _ = queued(readiness_db)
    final = store.claim_due(conn, now=NOW, lease_seconds=5, max_attempts=1)
    conn.commit()
    later = NOW + timedelta(seconds=5)
    assert store.claim_due(conn, now=later, max_attempts=1) is None
    conn.commit()
    assert conn.execute("select status,attempts,last_error_code,lease_token,lease_until from remote_work_readiness_job").fetchone() == (
        "blocked", final.attempts, "lease_expired", None, None)


@pytest.mark.parametrize("answer", [Answer(True), Answer(float('nan')), Answer(float('inf')), Answer(-0.1), Answer(1.1)])
def test_invalid_fraction_cannot_be_completed(readiness_db, answer):
    from job_machine.remote_readiness import store
    conn, _, _ = queued(readiness_db)
    job = store.claim_due(conn, now=NOW)
    with pytest.raises(ValueError):
        store.complete(conn, job, answer, now=NOW)
    assert conn.execute("select value from remote_work_readiness_job").fetchone() == (None,)


@pytest.mark.parametrize("answer", [Answer(0.5, model="other"), Answer(0.5, rubric_version="other")])
def test_result_version_mismatch_rejected(readiness_db, answer):
    from job_machine.remote_readiness import store
    conn, _, _ = queued(readiness_db)
    job = store.claim_due(conn, now=NOW)
    conn.commit()
    assert not store.complete(conn, job, answer, now=NOW)
    assert conn.execute("select status,value from remote_work_readiness_job").fetchone() == ("processing", None)


def test_failed_cas_preserves_caller_transaction(readiness_db):
    from job_machine.remote_readiness import store
    conn, _, value = queued(readiness_db)
    job = store.claim_due(conn, now=NOW)
    conn.commit()
    conn.execute("update vacancy set title='Synthetic changed' where vacancy_id=%s", (value.vacancy_id,))
    assert not store.complete(conn, replace(job, lease_token=uuid4()), Answer(0.4), now=NOW)
    assert not store.fail(conn, replace(job, lease_token=uuid4()), Error(), now=NOW)
    assert not store.rearm_blocked(conn, value.vacancy_id, now=NOW)
    assert conn.execute("select title from vacancy where vacancy_id=%s", (value.vacancy_id,)).fetchone() == ("Synthetic changed",)
    conn.rollback()
    assert conn.execute("select title from vacancy where vacancy_id=%s", (value.vacancy_id,)).fetchone() == ("Synthetic QA",)


@pytest.mark.parametrize("seconds", [0, -1, True, 1.5])
def test_invalid_lease_duration(readiness_db, seconds):
    from job_machine.remote_readiness import store
    conn, _, _ = queued(readiness_db)
    with pytest.raises(ValueError):
        store.claim_due(conn, now=NOW, lease_seconds=seconds)


def test_failure_keeps_only_sanitized_code(readiness_db):
    from job_machine.remote_readiness import store
    conn, _, _ = queued(readiness_db)
    job = store.claim_due(conn, now=NOW)
    assert store.fail(conn, job, Error("raw response should not persist", False), now=NOW)
    assert conn.execute("select last_error_code,value from remote_work_readiness_job").fetchone() == ("readiness_error", None)
