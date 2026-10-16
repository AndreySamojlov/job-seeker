"""Immutable fit snapshots and fenced worker leases; callers own commits.

An unsuccessful completion/failure CAS rolls back the transaction. Use a dedicated
short transaction for each operation; commit a claim before calling the API.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
import math
import re
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb

from .models import FitError, FitInput, FitResult
from .rubric import MODEL_ID, RUBRIC_VERSION, build_payload, payload_hash


@dataclass(frozen=True)
class ClaimedJob:
    candidate_id: str
    vacancy_id: UUID
    payload: dict
    payload_hash: str
    lease_token: UUID
    attempts: int


def create_job(conn, input: FitInput) -> bool:
    """Assign one prepared pair. A duplicate never replaces its first snapshot."""
    payload = build_payload(input)
    row = conn.execute(
        """insert into fit_job(candidate_id,vacancy_id,payload,payload_hash,model,rubric_version)
           values (%s,%s,%s,%s,%s,%s)
           on conflict (candidate_id,vacancy_id) do nothing returning candidate_id""",
        (input.candidate_id, input.vacancy_id, Jsonb(payload), payload_hash(payload),
         MODEL_ID, RUBRIC_VERSION),
    ).fetchone()
    return row is not None


def claim_due(conn, *, now: datetime, lease_seconds: int = 60) -> ClaimedJob | None:
    """Claim one due pair, or reclaim an expired lease without altering its input."""
    if isinstance(lease_seconds, bool) or not isinstance(lease_seconds, int) or lease_seconds <= 0:
        raise ValueError("invalid_lease_seconds")
    row = conn.execute(
        """with due as (
             select candidate_id,vacancy_id from fit_job
             where status='pending'
                or (status='retry_wait' and next_attempt_at <= %s)
                or (status='processing' and lease_until <= %s)
             order by created_at,candidate_id,vacancy_id
             for update skip locked limit 1
           )
           update fit_job j set status='processing',lease_token=%s,lease_until=%s,
                  attempts=j.attempts+1,next_attempt_at=null,updated_at=%s
           from due where j.candidate_id=due.candidate_id and j.vacancy_id=due.vacancy_id
           returning j.candidate_id,j.vacancy_id,j.payload,j.payload_hash,j.lease_token,j.attempts""",
        (now, now, uuid4(), now + timedelta(seconds=lease_seconds), now),
    ).fetchone()
    return ClaimedJob(*row) if row else None


def complete(conn, job: ClaimedJob, result: FitResult, *, now: datetime) -> bool:
    """Accept a validated result only from the current unexpired lease owner."""
    if (isinstance(result.score, bool) or not isinstance(result.score, int)
            or not 0 <= result.score <= 100):
        raise FitError("invalid_score")
    row = conn.execute(
        """update fit_job set status='completed',score=%s,completed_at=%s,updated_at=%s,
                  lease_token=null,lease_until=null,next_attempt_at=null,last_error_code=null
           where candidate_id=%s and vacancy_id=%s and status='processing'
             and lease_token=%s and lease_until > %s and payload_hash=%s
             and model=%s and rubric_version=%s returning candidate_id""",
        (result.score, now, now, job.candidate_id, job.vacancy_id, job.lease_token,
         now, job.payload_hash, result.model, result.rubric_version),
    ).fetchone()
    if row is None:
        conn.rollback()
    return row is not None


def fail(conn, job: ClaimedJob, error: FitError, *, now: datetime) -> bool:
    """Schedule bounded exponential retry or block, without storing raw messages."""
    delay = min(3600, 30 * 2 ** min(max(job.attempts - 1, 0), 7))
    retry_after = error.retry_after_seconds
    if (isinstance(retry_after, (int, float)) and not isinstance(retry_after, bool)
            and math.isfinite(retry_after) and retry_after >= 0):
        delay = max(delay, retry_after)
    # Preserve even an unusually long provider delay without datetime overflow.
    latest = datetime.max.replace(tzinfo=now.tzinfo)
    retry_at = now + timedelta(seconds=delay) if delay < (latest - now).total_seconds() else latest
    # FitError is a public boundary: accept only diagnostic code identifiers.
    code = error.code if isinstance(error.code, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,63}", error.code) else "fit_error"
    row = conn.execute(
        """update fit_job set status=%s,next_attempt_at=%s,last_error_code=%s,
                  lease_token=null,lease_until=null,updated_at=%s
           where candidate_id=%s and vacancy_id=%s and status='processing'
             and lease_token=%s and lease_until > %s and payload_hash=%s
           returning candidate_id""",
        ("retry_wait" if error.retryable else "blocked",
         retry_at if error.retryable else None,
         code, now, job.candidate_id, job.vacancy_id, job.lease_token, now, job.payload_hash),
    ).fetchone()
    if row is None:
        conn.rollback()
    return row is not None


def rearm_blocked(conn, candidate_id: str, vacancy_id: UUID, *, now: datetime) -> bool:
    """Resume the first assessment after its technical blocker is resolved."""
    row = conn.execute(
        """update fit_job set status='retry_wait',next_attempt_at=%s,
                  last_error_code=null,updated_at=%s
           where candidate_id=%s and vacancy_id=%s and status='blocked'
           returning candidate_id""",
        (now, now, candidate_id, vacancy_id),
    ).fetchone()
    if row is None:
        conn.rollback()
    return row is not None
