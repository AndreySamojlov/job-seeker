"""Run one leased readiness assessment without holding a DB transaction over HTTP."""
from datetime import datetime
from typing import Callable

from . import store
from .jev import make_jev_handler
from .models import ReadinessError
from .rules import READINESS_CATALOG, invoke_readiness


def run_once(conn_factory, *, client, api_key: str, clock: Callable[[], datetime],
             max_attempts=store.MAX_ATTEMPTS, timeout_seconds=30) -> str:
    """Claim one due snapshot, pass it through Rules to Jev, then fence its result."""
    with conn_factory() as conn:
        job = store.claim_due(conn, now=clock(), max_attempts=max_attempts)
        conn.commit()
    if job is None:
        return "idle"

    failure = None
    try:
        handler = make_jev_handler(client=client, api_key=api_key, timeout_seconds=timeout_seconds)
        answer = invoke_readiness(job.payload, READINESS_CATALOG, {"jev": handler})
    except ReadinessError as error:
        failure = error
    except Exception:
        # Unknown handler/configuration failures are permanent and kept safe.
        failure = ReadinessError("handler_error")

    if failure is not None:
        with conn_factory() as conn:
            accepted = store.fail(conn, job, failure, now=clock(), max_attempts=max_attempts)
            if accepted:
                conn.commit()
            else:
                conn.rollback()
        if not accepted:
            return "lease_lost"
        return "retry_wait" if failure.retryable else "blocked"

    with conn_factory() as conn:
        accepted = store.complete(conn, job, answer, now=clock())
        if accepted:
            conn.commit()
        else:
            conn.rollback()
    return "completed" if accepted else "lease_lost"
