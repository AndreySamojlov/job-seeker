"""Intake persistence tests; run only through scripts/check_schema.py db."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from tests.conftest import apply_migrations

pytestmark = pytest.mark.db
NOW = datetime(2030, 1, 1, tzinfo=timezone.utc)


@pytest.fixture
def intake_db(db_schema):
    conn, schema = db_schema
    apply_migrations(conn)
    from job_machine.remote_readiness import intake_store
    ids = [uuid4() for _ in range(3)]
    for vacancy_id, mode, status in [(ids[0], "unknown", "verified"),
                                     (ids[1], "onsite", "verified"),
                                     (ids[2], "hybrid", "discovered")]:
        conn.execute("insert into vacancy(vacancy_id,work_mode,vacancy_status) values (%s,%s,%s)",
                     (vacancy_id, mode, status))
    conn.commit()
    return conn, schema, ids


def test_enqueue_selects_only_verified_nononsite_once(intake_db):
    from job_machine.remote_readiness import intake_store
    conn, _, ids = intake_db
    assert intake_store.enqueue_verified(conn, limit=10) == 1
    conn.commit()
    assert intake_store.enqueue_verified(conn, limit=10) == 0
    assert conn.execute("select vacancy_id,status from remote_work_readiness_intake").fetchall() == [(ids[0], "pending")]


def test_intake_claim_is_bounded_and_lease_fenced(intake_db):
    from job_machine.remote_readiness import intake_store
    conn, _, ids = intake_db
    intake_store.enqueue_verified(conn, limit=10)
    conn.commit()
    claim = intake_store.claim_due(conn, now=NOW)
    conn.commit()
    assert claim.vacancy_id == ids[0]
    assert intake_store.fail(conn, claim, _Error(), now=NOW)
    conn.commit()
    assert intake_store.claim_due(conn, now=NOW + timedelta(seconds=29)) is None
    retry = intake_store.claim_due(conn, now=NOW + timedelta(seconds=30))
    conn.commit()
    assert retry.vacancy_id == ids[0] and retry.attempts == 2
    assert not intake_store.fail(conn, claim, _Error(), now=NOW + timedelta(seconds=30))


def test_configured_attempt_limit_blocks_intake_retry_at_limit(intake_db):
    from job_machine.remote_readiness import intake_store
    conn, _, _ = intake_db
    intake_store.enqueue_verified(conn, limit=10)
    conn.commit()
    first = intake_store.claim_due(conn, now=NOW, max_attempts=2)
    assert intake_store.fail(conn, first, _Error(), now=NOW, max_attempts=2)
    conn.commit()
    second = intake_store.claim_due(conn, now=NOW + timedelta(seconds=30), max_attempts=2)
    assert second.attempts == 2
    assert intake_store.fail(conn, second, _Error(), now=NOW + timedelta(seconds=30), max_attempts=2)
    conn.commit()
    assert conn.execute("select status from remote_work_readiness_intake").fetchone() == ("blocked",)
    assert intake_store.claim_due(conn, now=NOW + timedelta(days=1), max_attempts=2) is None


def test_crashed_final_intake_lease_expires_to_blocked(intake_db):
    from job_machine.remote_readiness import intake_store
    conn, _, _ = intake_db
    intake_store.enqueue_verified(conn, limit=10)
    conn.commit()
    final = intake_store.claim_due(conn, now=NOW, lease_seconds=5, max_attempts=1)
    conn.commit()
    later = NOW + timedelta(seconds=5)
    assert intake_store.claim_due(conn, now=later, max_attempts=1) is None
    conn.commit()
    assert conn.execute("select status,attempts,last_error_code,lease_token,lease_until from remote_work_readiness_intake").fetchone() == (
        "blocked", final.attempts, "lease_expired", None, None)


def test_snapshot_and_intake_completion_commit_as_one_unit(intake_db):
    from job_machine.remote_readiness import intake_store
    from job_machine.remote_readiness.store import ReadinessInput
    conn, _, ids = intake_db
    intake_store.enqueue_verified(conn, limit=10)
    conn.commit()
    claim = intake_store.claim_due(conn, now=NOW)
    conn.commit()
    payload = {"model": "jev-1.13.0", "state": {"rubric_version": "rwr-1", "job_text": "Ad"},
               "questions": {"remote_work_readiness": {"type": "noul"}}}
    assert intake_store.finish_with_snapshot(
        conn, claim, ReadinessInput(ids[0], "Ad", "unknown"), payload, now=NOW)
    conn.commit()
    assert conn.execute("select status from remote_work_readiness_intake").fetchone() == ("completed",)
    assert conn.execute("select payload->'state'->>'job_text' from remote_work_readiness_job").fetchone() == ("Ad",)


def test_failed_snapshot_transaction_does_not_complete_intake(intake_db):
    from job_machine.remote_readiness import intake_store
    from job_machine.remote_readiness.store import ReadinessInput
    conn, _, ids = intake_db
    intake_store.enqueue_verified(conn, limit=10)
    conn.commit()
    claim = intake_store.claim_due(conn, now=NOW)
    conn.commit()
    with pytest.raises(ValueError):
        intake_store.finish_with_snapshot(conn, claim, ReadinessInput(ids[0], "Ad", "unknown"), {}, now=NOW)
    conn.rollback()
    assert conn.execute("select status from remote_work_readiness_intake").fetchone() == ("processing",)


def test_gone_vacancy_uses_fixed_audit_function(intake_db):
    from job_machine.remote_readiness import intake_store
    conn, _, ids = intake_db
    intake_store.enqueue_verified(conn, limit=10)
    conn.commit()
    claim = intake_store.claim_due(conn, now=NOW)
    conn.commit()

    assert intake_store.finish_gone(conn, claim, now=NOW)
    conn.commit()

    assert conn.execute("select vacancy_status from vacancy where vacancy_id=%s", (ids[0],)).fetchone() == ("stale",)
    assert conn.execute("select status,last_error_code from remote_work_readiness_intake where vacancy_id=%s", (ids[0],)).fetchone() == ("blocked", "vacancy_gone")
    assert conn.execute(
        "select entity_type,event_type,payload_json,trace_id from event where entity_id=%s order by event_id desc limit 1",
        (ids[0],),
    ).fetchone() == ("vacancy", "vacancy.stale", {}, None)


class _Error:
    code = "ats_timeout"
    retryable = True
