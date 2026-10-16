"""One leased evaluation; database transactions never surround HTTP."""
from . import store
from .jev import evaluate_payload
from .models import FitError


def run_once(conn_factory, *, client, api_key, clock):
    with conn_factory() as conn:
        job = store.claim_due(conn, now=clock())
        conn.commit()
    if job is None:
        return "idle"
    try:
        if not api_key or not api_key.strip():
            raise FitError("missing_api_key", retryable=False)
        result = evaluate_payload(job.payload, client=client, api_key=api_key)
    except FitError as error:
        with conn_factory() as conn:
            accepted = store.fail(conn, job, error, now=clock())
            if accepted:
                conn.commit()
            else:
                conn.rollback()
        return ("retry_wait" if error.retryable else "blocked") if accepted else "lease_lost"
    with conn_factory() as conn:
        accepted = store.complete(conn, job, result, now=clock())
        if accepted:
            conn.commit()
        else:
            conn.rollback()
    return "completed" if accepted else "lease_lost"
