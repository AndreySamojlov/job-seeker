"""Immutable provider snapshots and fenced leases; callers own transactions.

Commit claims before provider HTTP. Each operation belongs in a short dedicated
transaction. No operation commits or rolls back unrelated caller work.
"""
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
import json
import math
import re
from typing import Protocol
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb

MAX_ATTEMPTS = 8


@dataclass(frozen=True)
class ReadinessInput:
    vacancy_id: UUID
    job_text: str
    work_mode: str


@dataclass(frozen=True)
class ClaimedReadinessJob:
    vacancy_id: UUID
    payload: dict
    payload_hash: str
    lease_token: UUID
    attempts: int


class ReadinessAnswer(Protocol):
    value: float
    model: str
    rubric_version: str


class ReadinessFailure(Protocol):
    code: str
    retryable: bool
    retry_after_seconds: float | None


def create_job(conn, input: ReadinessInput, *, payload: Mapping[str, object]) -> bool:
    """Assign once, retaining the exact provider payload supplied by the caller."""
    if input.work_mode == "onsite":
        return False
    # Serialize once, detach nested mutable caller data, and hash identical bytes.
    encoded = json.dumps(dict(payload), ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    snapshot = json.loads(encoded)
    model = snapshot.get("model")
    state = snapshot.get("state")
    rubric = state.get("rubric_version") if isinstance(state, dict) else None
    if not isinstance(model, str) or not model or not isinstance(rubric, str) or not rubric:
        raise ValueError("invalid_snapshot_versions")
    row = conn.execute(
        """insert into remote_work_readiness_job(vacancy_id,payload,payload_hash,model,rubric_version)
           values (%s,%s,%s,%s,%s) on conflict (vacancy_id) do nothing returning vacancy_id""",
        (input.vacancy_id, Jsonb(snapshot), hashlib.sha256(encoded).hexdigest(), model, rubric),
    ).fetchone()
    return row is not None


def claim_due(conn, *, now: datetime, lease_seconds: int = 60,
              max_attempts: int = MAX_ATTEMPTS) -> ClaimedReadinessJob | None:
    """Claim due work without blocking another worker or replacing its snapshot."""
    if isinstance(lease_seconds, bool) or not isinstance(lease_seconds, int) or lease_seconds <= 0:
        raise ValueError("invalid_lease_seconds")
    if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or not 1 <= max_attempts <= 8:
        raise ValueError("invalid_max_attempts")
    # Close expired final leases so a worker crash cannot strand work forever
    # in processing. This bounded cleanup never touches a live lease.
    conn.execute(
        """with exhausted as (
             select vacancy_id from remote_work_readiness_job
             where status='processing' and lease_until<=%s and attempts>=%s
             order by lease_until,created_at,vacancy_id
             for update skip locked limit 100
           )
           update remote_work_readiness_job j
           set status='blocked',last_error_code='lease_expired',lease_token=null,
               lease_until=null,next_attempt_at=null,updated_at=%s
           from exhausted where j.vacancy_id=exhausted.vacancy_id""",
        (now, max_attempts, now),
    )
    row = conn.execute(
        """with due as (
             select vacancy_id from remote_work_readiness_job
             where (status='pending' and attempts < %s)
                or (status='retry_wait' and next_attempt_at <= %s and attempts < %s)
                or (status='processing' and lease_until <= %s and attempts < %s)
             order by created_at,vacancy_id for update skip locked limit 1
           )
           update remote_work_readiness_job j
           set status='processing',lease_token=%s,lease_until=%s,
               attempts=j.attempts+1,next_attempt_at=null,updated_at=%s
           from due where j.vacancy_id=due.vacancy_id
           returning j.vacancy_id,j.payload,j.payload_hash,j.lease_token,j.attempts""",
        (max_attempts, now, max_attempts, now, max_attempts,
         uuid4(), now + timedelta(seconds=lease_seconds), now),
    ).fetchone()
    return ClaimedReadinessJob(*row) if row else None


def complete(conn, job: ClaimedReadinessJob, answer: ReadinessAnswer, *, now: datetime) -> bool:
    """Save the original finite provider fraction only for the live lease owner."""
    value = answer.value
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not 0 <= value <= 1 or not math.isfinite(value)):
        raise ValueError("invalid_readiness_value")
    row = conn.execute(
        """update remote_work_readiness_job
           set status='completed',value=%s,completed_at=%s,updated_at=%s,
               lease_token=null,lease_until=null,next_attempt_at=null,last_error_code=null
           where vacancy_id=%s and status='processing' and lease_token=%s
             and lease_until > %s and payload_hash=%s and model=%s and rubric_version=%s
           returning vacancy_id""",
        (value, now, now, job.vacancy_id, job.lease_token, now, job.payload_hash,
         answer.model, answer.rubric_version),
    ).fetchone()
    return row is not None


def fail(conn, job: ClaimedReadinessJob, error: ReadinessFailure, *, now: datetime,
         max_attempts: int = MAX_ATTEMPTS) -> bool:
    """Retry with the same input or block, retaining only a safe diagnostic code."""
    if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or not 1 <= max_attempts <= 8:
        raise ValueError("invalid_max_attempts")
    delay = min(3600, 30 * 2 ** min(max(job.attempts - 1, 0), 7))
    retry_after = error.retry_after_seconds
    if (isinstance(retry_after, (int, float)) and not isinstance(retry_after, bool)
            and math.isfinite(retry_after) and retry_after >= 0):
        delay = max(delay, retry_after)
    latest = datetime.max.replace(tzinfo=now.tzinfo)
    retry_at = now + timedelta(seconds=delay) if delay < (latest - now).total_seconds() else latest
    code = error.code if isinstance(error.code, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,63}", error.code) else "readiness_error"
    row = conn.execute(
        """update remote_work_readiness_job
           set status=%s,next_attempt_at=%s,last_error_code=%s,
               lease_token=null,lease_until=null,updated_at=%s
           where vacancy_id=%s and status='processing' and lease_token=%s
             and lease_until > %s and payload_hash=%s returning vacancy_id""",
        ("retry_wait" if error.retryable and job.attempts < max_attempts else "blocked",
         retry_at if error.retryable and job.attempts < max_attempts else None,
         code, now, job.vacancy_id, job.lease_token, now, job.payload_hash),
    ).fetchone()
    return row is not None


def rearm_blocked(conn, vacancy_id: UUID, *, now: datetime) -> bool:
    """Explicitly resume a blocked first assessment after its cause is resolved."""
    return conn.execute(
        """update remote_work_readiness_job
           set status='retry_wait',next_attempt_at=%s,attempts=0,last_error_code=null,updated_at=%s
           where vacancy_id=%s and status='blocked' returning vacancy_id""",
        (now, now, vacancy_id),
    ).fetchone() is not None
