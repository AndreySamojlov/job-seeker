"""Preparation queue operations. Callers own short transactions and commits."""
from dataclasses import dataclass
from datetime import timedelta
import re
from uuid import uuid4


@dataclass(frozen=True)
class ClaimedPreparation:
    vacancy_id: object
    job_text: str | None
    lease_token: object
    attempts: int


def claim_due(conn, *, now, lease_seconds=60):
    if isinstance(lease_seconds, bool) or not isinstance(lease_seconds, int) or lease_seconds <= 0:
        raise ValueError('invalid_lease_seconds')
    row = conn.execute("""with due as (
      select vacancy_id from fit_prepare where status='pending'
        or (status='retry_wait' and next_attempt_at<=%s)
        or (status='processing' and lease_until<=%s)
      order by created_at,vacancy_id for update skip locked limit 1)
      update fit_prepare p set status='processing', attempts=p.attempts+1,
        lease_token=%s,lease_until=%s,next_attempt_at=null,updated_at=%s
      from due where p.vacancy_id=due.vacancy_id
      returning p.vacancy_id,p.job_text,p.lease_token,p.attempts""",
      (now, now, uuid4(), now+timedelta(seconds=lease_seconds), now)).fetchone()
    return ClaimedPreparation(*row) if row else None


def _fence(conn, job, now):
    return conn.execute("""select vacancy_id from fit_prepare where vacancy_id=%s
      and status='processing' and lease_token=%s and lease_until>%s for update""",
      (job.vacancy_id,job.lease_token,now)).fetchone() is not None


def renew_lease(conn, job, *, now, lease_seconds=360):
    if isinstance(lease_seconds, bool) or not isinstance(lease_seconds, int) or lease_seconds <= 0:
        raise ValueError('invalid_lease_seconds')
    row = conn.execute("""update fit_prepare set lease_until=%s,updated_at=%s
      where vacancy_id=%s and status='processing' and lease_token=%s and lease_until>%s
      returning vacancy_id""",
      (now+timedelta(seconds=lease_seconds),now,job.vacancy_id,job.lease_token,now)).fetchone()
    return row is not None


def save_text(conn, job, text, *, now):
    if not _fence(conn, job, now):
        conn.rollback()
        return False
    conn.execute('update fit_prepare set job_text=coalesce(job_text,%s),updated_at=%s where vacancy_id=%s', (text,now,job.vacancy_id))
    return True


def due_children(conn, job, *, now):
    return [r[0] for r in conn.execute("""select candidate_id from fit_prepare_candidate
      where vacancy_id=%s and (status='pending' or (status='retry_wait' and next_attempt_at<=%s))
      order by candidate_id""", (job.vacancy_id,now)).fetchall()]


def prepare_child(conn, job, candidate_id, *, now):
    if not _fence(conn, job, now):
        conn.rollback()
        return False
    row = conn.execute("""update fit_prepare_candidate set status='prepared', attempts=attempts+1,
      next_attempt_at=null,last_error_code=null,updated_at=%s,prepared_at=%s
      where vacancy_id=%s and candidate_id=%s and status in ('pending','retry_wait') returning candidate_id""",
      (now,now,job.vacancy_id,candidate_id)).fetchone()
    return row is not None


def _failure(error, attempts, now):
    code = error.code if isinstance(error.code,str) and re.fullmatch('[a-z][a-z0-9_]{0,63}',error.code) else 'preparation_error'
    return ('retry_wait' if error.retryable else 'blocked',
            now+timedelta(seconds=min(3600,30*2**min(max(attempts-1,0),7))) if error.retryable else None,code)


def fail_child(conn, job, candidate_id, error, *, now):
    if not _fence(conn,job,now):
        conn.rollback()
        return False
    row = conn.execute('select attempts from fit_prepare_candidate where vacancy_id=%s and candidate_id=%s', (job.vacancy_id,candidate_id)).fetchone()
    if row is None:
        return False
    status,next_at,code = _failure(error,row[0]+1,now)
    conn.execute("""update fit_prepare_candidate set status=%s,attempts=attempts+1,
      next_attempt_at=%s,last_error_code=%s,updated_at=%s where vacancy_id=%s and candidate_id=%s""",
      (status,next_at,code,now,job.vacancy_id,candidate_id))
    return True


def fail(conn, job, error, *, now):
    if not _fence(conn,job,now):
        conn.rollback()
        return False
    status,next_at,code = _failure(error,job.attempts,now)
    conn.execute("""update fit_prepare set status=%s,next_attempt_at=%s,last_error_code=%s,
      lease_token=null,lease_until=null,updated_at=%s where vacancy_id=%s""", (status,next_at,code,now,job.vacancy_id))
    return True


def finish(conn, job, *, now):
    if not _fence(conn,job,now):
        conn.rollback()
        return 'lease_lost'
    rows = conn.execute('select status,next_attempt_at from fit_prepare_candidate where vacancy_id=%s', (job.vacancy_id,)).fetchall()
    retries = [r[1] for r in rows if r[0]=='retry_wait']
    status = 'retry_wait' if retries or any(r[0]=='pending' for r in rows) else 'blocked' if any(r[0]=='blocked' for r in rows) else 'completed'
    conn.execute("""update fit_prepare set status=%s,next_attempt_at=%s,lease_token=null,
      lease_until=null,last_error_code=null,updated_at=%s,completed_at=%s where vacancy_id=%s""",
      (status,min(retries) if retries else now if status=='retry_wait' else None,now,now if status=='completed' else None,job.vacancy_id))
    return 'prepared' if status=='completed' else status


def rearm_blocked(conn, vacancy_id, *, candidate_id=None, now):
    # Lock parent first, following the worker's order.
    row = conn.execute("select status from fit_prepare where vacancy_id=%s for update", (vacancy_id,)).fetchone()
    if row is None or row[0]=='processing':
        return False
    params = [now,now,vacancy_id]
    suffix = ''
    if candidate_id is not None:
        suffix = ' and candidate_id=%s'
        params.append(candidate_id)
    changed = conn.execute("""update fit_prepare_candidate set status='retry_wait',next_attempt_at=%s,
      updated_at=%s,last_error_code=null where vacancy_id=%s and status='blocked'"""+suffix+' returning candidate_id',params).fetchall()
    if changed or (row[0]=='blocked' and candidate_id is None):
        conn.execute("""update fit_prepare set status='retry_wait',next_attempt_at=%s,
          updated_at=%s,last_error_code=null where vacancy_id=%s""", (now,now,vacancy_id))
        return True
    return False
