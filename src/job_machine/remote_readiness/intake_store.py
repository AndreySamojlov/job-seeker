"""Durable pre-snapshot intake queue. Callers own short transactions."""
from dataclasses import dataclass, replace
from datetime import timedelta
import re
from uuid import uuid4

from . import store as readiness_store

MAX_ATTEMPTS = 8


@dataclass(frozen=True)
class ClaimedIntake:
    vacancy_id: object
    lease_token: object
    attempts: int


def enqueue_verified(conn, *, limit: int) -> int:
    """Enqueue a bounded batch of verified, non-onsite vacancies exactly once."""
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise ValueError("invalid_limit")
    if limit <= 0:
        return 0
    rows = conn.execute(
        """with candidates as (
             select v.vacancy_id from vacancy v
             where v.vacancy_status='verified' and v.work_mode is distinct from 'onsite'
               and not exists (select 1 from remote_work_readiness_intake i where i.vacancy_id=v.vacancy_id)
               and not exists (select 1 from remote_work_readiness_job j where j.vacancy_id=v.vacancy_id)
             order by v.verified_at nulls first,v.discovered_at nulls first,v.vacancy_id
             limit %s
           )
           insert into remote_work_readiness_intake(vacancy_id)
           select vacancy_id from candidates on conflict (vacancy_id) do nothing
           returning vacancy_id""",
        (limit,),
    ).fetchall()
    return len(rows)


def claim_due(conn, *, now, lease_seconds=60, max_attempts=MAX_ATTEMPTS):
    if isinstance(lease_seconds, bool) or not isinstance(lease_seconds, int) or lease_seconds <= 0:
        raise ValueError("invalid_lease_seconds")
    if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or not 1 <= max_attempts <= 8:
        raise ValueError("invalid_max_attempts")
    # A worker may crash after taking its final permitted lease. Expiry must
    # close that row explicitly; otherwise it is neither claimable nor visible
    # as a terminal failure. Keep cleanup bounded and respect concurrent owners.
    conn.execute(
        """with exhausted as (
             select vacancy_id from remote_work_readiness_intake
             where status='processing' and lease_until<=%s and attempts>=%s
             order by lease_until,created_at,vacancy_id
             for update skip locked limit 100
           )
           update remote_work_readiness_intake i
           set status='blocked',last_error_code='lease_expired',lease_token=null,
               lease_until=null,next_attempt_at=null,updated_at=%s
           from exhausted where i.vacancy_id=exhausted.vacancy_id""",
        (now, max_attempts, now),
    )
    row = conn.execute(
        """with due as (
             select vacancy_id from remote_work_readiness_intake
             where (status='pending' and attempts < %s)
                or (status='retry_wait' and next_attempt_at<=%s and attempts < %s)
                or (status='processing' and lease_until<=%s and attempts < %s)
             order by created_at,vacancy_id for update skip locked limit 1
           )
           update remote_work_readiness_intake i
           set status='processing',attempts=i.attempts+1,lease_token=%s,
               lease_until=%s,next_attempt_at=null,updated_at=%s
           from due where i.vacancy_id=due.vacancy_id
           returning i.vacancy_id,i.lease_token,i.attempts""",
        (max_attempts, now, max_attempts, now, max_attempts,
         uuid4(), now + timedelta(seconds=lease_seconds), now),
    ).fetchone()
    return ClaimedIntake(*row) if row else None


def _code(error):
    code = getattr(error, "code", "")
    return code if isinstance(code, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,63}", code) else "intake_error"


def fail(conn, job, error, *, now, max_attempts=MAX_ATTEMPTS):
    if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or not 1 <= max_attempts <= 8:
        raise ValueError("invalid_max_attempts")
    retryable = getattr(error, "retryable", False) is True and job.attempts < max_attempts
    delay = min(3600, 30 * 2 ** min(max(job.attempts - 1, 0), 7))
    return conn.execute(
        """update remote_work_readiness_intake
           set status=%s,next_attempt_at=%s,last_error_code=%s,
               lease_token=null,lease_until=null,updated_at=%s
           where vacancy_id=%s and status='processing' and lease_token=%s
             and lease_until>%s returning vacancy_id""",
        ("retry_wait" if retryable else "blocked", now + timedelta(seconds=delay) if retryable else None,
         _code(error), now, job.vacancy_id, job.lease_token, now),
    ).fetchone() is not None


def finish_with_snapshot(conn, job, readiness_input, payload, *, now):
    """Fence eligibility, create S1 snapshot, and finish intake atomically."""
    owned = conn.execute(
        """select vacancy_id from remote_work_readiness_intake
           where vacancy_id=%s and status='processing' and lease_token=%s
             and lease_until>%s for update""",
        (job.vacancy_id, job.lease_token, now),
    ).fetchone()
    if owned is None:
        return "lease_lost"
    row = conn.execute(
        """select vacancy_status,work_mode from vacancy where vacancy_id=%s for update""",
        (job.vacancy_id,),
    ).fetchone()
    if row is None or row[0] != "verified" or row[1] == "onsite":
        return "blocked" if _finish_blocked(conn, job, "not_eligible", now) else "lease_lost"
    value = replace(readiness_input, work_mode=row[1] or "unknown")
    created = readiness_store.create_job(conn, value, payload=payload)
    conn.execute("update vacancy set verified_at=%s where vacancy_id=%s", (now, job.vacancy_id))
    row = conn.execute(
        """update remote_work_readiness_intake
           set status='completed',completed_at=%s,updated_at=%s,last_error_code=null,
               lease_token=null,lease_until=null,next_attempt_at=null
           where vacancy_id=%s and status='processing' and lease_token=%s and lease_until>%s
           returning vacancy_id""",
        (now, now, job.vacancy_id, job.lease_token, now),
    ).fetchone()
    if row is None:
        return "lease_lost"
    return "prepared" if created else "existing"


def finish_existing(conn, job, *, now):
    """Close a duplicate intake without rechecking ATS after an S1 snapshot exists."""
    row = conn.execute(
        """update remote_work_readiness_intake i
           set status='completed',completed_at=%s,updated_at=%s,last_error_code=null,
               lease_token=null,lease_until=null,next_attempt_at=null
           where i.vacancy_id=%s and i.status='processing' and i.lease_token=%s
             and i.lease_until>%s
             and exists (select 1 from remote_work_readiness_job j where j.vacancy_id=i.vacancy_id)
           returning i.vacancy_id""",
        (now, now, job.vacancy_id, job.lease_token, now),
    ).fetchone()
    return row is not None


def finish_gone(conn, job, *, now):
    """Record a freshly confirmed gone vacancy without creating an S1 row."""
    owned = conn.execute(
        """select vacancy_id from remote_work_readiness_intake
           where vacancy_id=%s and status='processing' and lease_token=%s
             and lease_until>%s for update""",
        (job.vacancy_id, job.lease_token, now),
    ).fetchone()
    if owned is None:
        return False
    conn.execute("select job_rwr_mark_vacancy_stale(%s)", (job.vacancy_id,))
    return _finish_blocked(conn, job, "vacancy_gone", now)


def finish_blocked(conn, job, code, *, now):
    safe_code = code if isinstance(code, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,63}", code) else "intake_error"
    return _finish_blocked(conn, job, safe_code, now)


def _finish_blocked(conn, job, code, now):
    return conn.execute(
        """update remote_work_readiness_intake set status='blocked',last_error_code=%s,
             lease_token=null,lease_until=null,next_attempt_at=null,updated_at=%s
           where vacancy_id=%s and status='processing' and lease_token=%s and lease_until>%s
           returning vacancy_id""",
        (code, now, job.vacancy_id, job.lease_token, now),
    ).fetchone() is not None


def rearm_blocked(conn, vacancy_id, *, now):
    return conn.execute(
        """update remote_work_readiness_intake set status='retry_wait',next_attempt_at=%s,
             attempts=0,last_error_code=null,updated_at=%s where vacancy_id=%s and status='blocked'
             returning vacancy_id""",
        (now, now, vacancy_id),
    ).fetchone() is not None
