"""Synthetic data only; refuse any database except the workspace recovery cluster."""
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


@pytest.fixture
def fit_db(db_schema):
    conn, schema = db_schema
    database, port, directory = conn.execute(
        "select current_database(),inet_server_port(),current_setting('data_directory')"
    ).fetchone()
    root = Path(__file__).resolve().parents[2]
    assert (database, port) == ("job_machine_recovery_test", 25439)
    assert Path(directory).resolve() == (root / ".runtime/pg-recovery").resolve()
    apply_migrations(conn)
    conn.execute("insert into candidate(candidate_id,name) values ('fit-synthetic','Synthetic')")
    conn.execute("insert into candidate(candidate_id,name) values ('other','Other Synthetic')")
    vacancy = uuid4()
    conn.execute("insert into vacancy(vacancy_id,title) values (%s,'Synthetic QA')", (vacancy,))
    conn.commit()
    from job_machine.fit.models import FitFact, FitInput
    value = FitInput("fit-synthetic", vacancy, "Synthetic vacancy", (
        FitFact("qa", "Synthetic QA experience", "verified", "synthetic"),
    ))
    return conn, schema, value


def queued(fit_db):
    from job_machine.fit import store
    conn, schema, value = fit_db
    assert store.create_job(conn, value)
    conn.commit()
    return conn, schema, value


def test_duplicate_keeps_original_snapshot_and_null_score(fit_db):
    from dataclasses import replace
    from job_machine.fit import store
    conn, _, value = queued(fit_db)
    before = conn.execute("select payload_hash,payload,score from fit_job").fetchone()
    assert before[2] is None
    assert not store.create_job(conn, replace(value, job_text="Changed"))
    assert conn.execute("select payload_hash,payload,score from fit_job").fetchone() == before
    assert "api_key" not in str(before[1]).lower()


@pytest.mark.parametrize("assignment", ["payload='{}'::jsonb", "payload_hash=repeat('0',64)",
                                        "model='other'", "rubric_version='other'",
                                        "candidate_id='other'"])
def test_saved_input_is_immutable(fit_db, assignment):
    conn, _, _ = queued(fit_db)
    with pytest.raises(psycopg.Error), conn.transaction():
        conn.execute("update fit_job set " + assignment)


def test_zero_complete_is_immutable_and_inactive_does_not_cancel(fit_db):
    from job_machine.fit import store
    from job_machine.fit.models import FitResult
    conn, _, _ = queued(fit_db)
    job = store.claim_due(conn, now=NOW)
    conn.commit()
    conn.execute("update candidate set active=false where candidate_id='fit-synthetic'")
    assert store.complete(conn, job, FitResult(0, "jev-1.13.0", "jfit-1"), now=NOW)
    conn.commit()
    assert conn.execute("select status,score from fit_job").fetchone() == ("completed", 0)
    for statement in ("update fit_job set score=99", "update fit_job set status='pending'",
                      "delete from fit_job"):
        with pytest.raises(psycopg.Error), conn.transaction():
            conn.execute(statement)


@pytest.mark.parametrize("score", [None, -1, 101])
def test_completed_requires_score_in_range(fit_db, score):
    conn, _, _ = queued(fit_db)
    with pytest.raises(psycopg.Error), conn.transaction():
        conn.execute("update fit_job set status='completed',completed_at=now(),score=%s", (score,))


def test_expired_and_superseded_leases_cannot_finish_or_fail(fit_db):
    from job_machine.fit import store
    from job_machine.fit.models import FitResult, FitError
    conn, _, _ = queued(fit_db)
    old = store.claim_due(conn, now=NOW, lease_seconds=5)
    conn.commit()
    result = FitResult(75, "jev-1.13.0", "jfit-1")
    assert not store.complete(conn, old, result, now=NOW + timedelta(seconds=5))
    new = store.claim_due(conn, now=NOW + timedelta(seconds=5))
    conn.commit()
    assert new.lease_token != old.lease_token
    assert new.attempts == 2
    assert new.payload_hash == old.payload_hash
    assert not store.complete(conn, old, result, now=NOW + timedelta(seconds=6))
    assert not store.fail(conn, old, FitError("timeout", True), now=NOW + timedelta(seconds=6))
    assert store.complete(conn, new, result, now=NOW + timedelta(seconds=6))


def test_claim_skips_locked_pair_and_store_never_commits(fit_db):
    from job_machine.fit import store
    conn, schema, _ = queued(fit_db)
    with psycopg.connect(os.environ["DATABASE_URL"]) as other:
        other.execute(sql.SQL("set search_path to {}").format(sql.Identifier(schema)))
        job = store.claim_due(conn, now=NOW)
        assert job is not None
        assert store.claim_due(other, now=NOW) is None
        conn.rollback()
        assert store.claim_due(other, now=NOW) is not None


def test_retry_delay_and_nonretryable_block(fit_db):
    from job_machine.fit import store
    from job_machine.fit.models import FitError
    conn, _, _ = queued(fit_db)
    job = store.claim_due(conn, now=NOW)
    assert store.fail(conn, job, FitError("rate_limit", True, 90), now=NOW)
    conn.commit()
    assert conn.execute("select status,next_attempt_at,score from fit_job").fetchone() == (
        "retry_wait", NOW + timedelta(seconds=90), None)
    assert store.claim_due(conn, now=NOW + timedelta(seconds=89)) is None
    job = store.claim_due(conn, now=NOW + timedelta(seconds=90))
    assert store.fail(conn, job, FitError("invalid_response", False), now=NOW + timedelta(seconds=90))
    conn.commit()
    assert conn.execute("select status,score,last_error_code from fit_job").fetchone() == (
        "blocked", None, "invalid_response")
    assert store.claim_due(conn, now=NOW + timedelta(days=1)) is None


def test_oversized_input_is_rejected_without_snapshot(fit_db):
    from dataclasses import replace
    from job_machine.fit import store
    from job_machine.fit.models import FitError
    conn, _, value = fit_db
    with pytest.raises(FitError) as caught:
        store.create_job(conn, replace(value, job_text="x" * 100_001))
    assert caught.value.code == "input_too_large"
    assert conn.execute("select count(*) from fit_job").fetchone()[0] == 0


@pytest.mark.parametrize("model,rubric", [("different", "jfit-1"), ("jev-1.13.0", "different")])
def test_completion_fences_result_versions_and_rolls_back_failed_cas(fit_db, model, rubric):
    from job_machine.fit import store
    from job_machine.fit.models import FitResult
    conn, _, _ = queued(fit_db)
    job = store.claim_due(conn, now=NOW)
    conn.commit()
    conn.execute("update candidate set headline='uncommitted' where candidate_id='fit-synthetic'")
    assert not store.complete(conn, job, FitResult(90, model, rubric), now=NOW)
    assert conn.execute("select headline from candidate where candidate_id='fit-synthetic'").fetchone() == ("",)
    assert conn.execute("select status,score from fit_job").fetchone() == ("processing", None)


def test_retry_after_longer_than_day_is_honored(fit_db):
    from job_machine.fit import store
    from job_machine.fit.models import FitError
    conn, _, _ = queued(fit_db)
    job = store.claim_due(conn, now=NOW)
    assert store.fail(conn, job, FitError("rate_limit", True, 172800), now=NOW)
    assert conn.execute("select next_attempt_at from fit_job").fetchone() == (NOW + timedelta(days=2),)


def test_rearm_only_blocked_preserves_snapshot_and_attempts(fit_db):
    from job_machine.fit import store
    from job_machine.fit.models import FitError, FitResult
    conn, _, value = queued(fit_db)
    assert not store.rearm_blocked(conn, value.candidate_id, value.vacancy_id, now=NOW)
    job = store.claim_due(conn, now=NOW)
    assert store.fail(conn, job, FitError("auth_rejected"), now=NOW)
    conn.commit()
    before = conn.execute("select payload,payload_hash,model,rubric_version,attempts from fit_job").fetchone()
    assert store.rearm_blocked(conn, value.candidate_id, value.vacancy_id, now=NOW)
    assert conn.execute("select payload,payload_hash,model,rubric_version,attempts from fit_job").fetchone() == before
    assert conn.execute("select status,next_attempt_at,last_error_code from fit_job").fetchone() == ("retry_wait", NOW, None)
    conn.rollback()
    assert conn.execute("select status from fit_job").fetchone() == ("blocked",)
    assert store.rearm_blocked(conn, value.candidate_id, value.vacancy_id, now=NOW)
    job = store.claim_due(conn, now=NOW)
    assert store.complete(conn, job, FitResult(50, "jev-1.13.0", "jfit-1"), now=NOW)
    conn.commit()
    assert not store.rearm_blocked(conn, value.candidate_id, value.vacancy_id, now=NOW)
    assert conn.execute("select status,score from fit_job").fetchone() == ("completed", 50)
