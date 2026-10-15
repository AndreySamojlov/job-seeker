import uuid
from datetime import datetime, timedelta, timezone

import pytest

from job_machine.db import migrate
from job_machine.submit import gate


def _apply(conn):
    for m in migrate.pending(migrate.discover_migrations("db/migrations"),
                             migrate.applied_migrations(conn)):
        migrate.apply_migration(conn, m)


def _seed_app(conn, payload_hash="ph1", state="pre_submit_ready"):
    with conn.cursor() as cur:
        cur.execute(
            "insert into vacancy (company, title, canonical_url, vacancy_status, state) "
            "values ('Acme','QA Lead','https://acme/gate','triaged','triaged') "
            "returning vacancy_id")
        vid = cur.fetchone()[0]
        cur.execute(
            "insert into application (vacancy_id, candidate_id, verdict, package_status, state, "
            "payload_hash) "
            "values (%s,'andrey-s','apply','none',%s,%s) returning application_id",
            (vid, state, payload_hash))
        return str(cur.fetchone()[0])


def _seed_approval(conn, application_id, status="approved", payload_hash="ph1",
                   hours_offset=24):
    expires = datetime.now(tz=timezone.utc) + timedelta(hours=hours_offset)
    with conn.cursor() as cur:
        cur.execute(
            "insert into approval (application_id, approval_type, payload_hash, "
            "approval_status, approval_token, expires_at, approved_at) "
            "values (%s,'submit',%s,%s,'tok64chars',%s,%s)",
            (uuid.UUID(application_id), payload_hash, status, expires,
             datetime.now(tz=timezone.utc) if status == "approved" else None))


@pytest.mark.db
def test_gate_stops_without_any_approval(db_schema):
    conn, _ = db_schema
    _apply(conn)
    aid = _seed_app(conn)
    conn.commit()
    result = gate.check_submit_gate(conn, aid, datetime.now(tz=timezone.utc))
    assert result is not None
    assert result.guard_name == "NoSubmitWithoutApproval"


@pytest.mark.db
def test_gate_stops_with_expired_approval(db_schema):
    conn, _ = db_schema
    _apply(conn)
    aid = _seed_app(conn)
    conn.commit()
    _seed_approval(conn, aid, status="approved", hours_offset=-1)
    conn.commit()
    result = gate.check_submit_gate(conn, aid, datetime.now(tz=timezone.utc))
    assert result is not None
    assert result.guard_name == "NoSubmitAfterApprovalExpiry"


@pytest.mark.db
def test_gate_stops_with_payload_hash_mismatch(db_schema):
    conn, _ = db_schema
    _apply(conn)
    aid = _seed_app(conn, payload_hash="hash_app")
    conn.commit()
    _seed_approval(conn, aid, payload_hash="hash_different")
    conn.commit()
    result = gate.check_submit_gate(conn, aid, datetime.now(tz=timezone.utc))
    assert result is not None
    assert result.guard_name == "NoSubmitIfPayloadHashChanged"


@pytest.mark.db
def test_gate_passes_with_valid_approved_matching_approval(db_schema):
    conn, _ = db_schema
    _apply(conn)
    aid = _seed_app(conn, payload_hash="goodhash")
    conn.commit()
    _seed_approval(conn, aid, payload_hash="goodhash", hours_offset=24)
    conn.commit()
    result = gate.check_submit_gate(conn, aid, datetime.now(tz=timezone.utc))
    assert result is None


@pytest.mark.db
def test_gate_stops_with_pending_approval(db_schema):
    conn, _ = db_schema
    _apply(conn)
    aid = _seed_app(conn, payload_hash="ph1")
    conn.commit()
    _seed_approval(conn, aid, status="pending")
    conn.commit()
    result = gate.check_submit_gate(conn, aid, datetime.now(tz=timezone.utc))
    assert result is not None
    assert result.guard_name == "NoSubmitWithoutApproval"


# --- check_resume_hash_gate unit tests (no DB) ---

def test_resume_hash_gate_passes_on_match():
    result = gate.check_resume_hash_gate(
        resume_artifact={"content_hash": "abc123"},
        disclosed_resume_hash="abc123",
    )
    assert result is None


def test_resume_hash_gate_stops_on_mismatch():
    result = gate.check_resume_hash_gate(
        resume_artifact={"content_hash": "abc123"},
        disclosed_resume_hash="different_hash",
    )
    assert result is not None
    assert result.guard_name == "NoResumeUploadWithoutHashMatch"


def test_resume_hash_gate_stops_if_no_disclosed_hash():
    result = gate.check_resume_hash_gate(
        resume_artifact={"content_hash": "abc123"},
        disclosed_resume_hash=None,
    )
    assert result is not None
    assert result.guard_name == "NoResumeUploadWithoutHashMatch"


def test_gate_stops_on_invalid_application_id():
    from job_machine.guards.base import Decision
    # conn=None: при кривом id гейт обрывается ДО обращения к БД
    result = gate.check_submit_gate(None, "not-a-uuid", datetime.now(tz=timezone.utc))
    assert result is not None
    assert result.guard_name == "ValidApplicationId"
    assert result.decision is Decision.STOP
