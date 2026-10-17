"""One leased evaluation; database transactions never surround HTTP."""
from datetime import timezone
from . import store
from .jev import evaluate_payload
from .models import FitError
from .quota import reserve_request as default_reserve_request, next_midnight


def run_once(conn_factory, *, client, api_key, clock, reserve_request=default_reserve_request, ats_family=None):
    with conn_factory() as conn:
        claimed_at = clock()
        kwargs = {'ats_family': ats_family} if ats_family is not None else {}
        job = store.claim_due(conn, now=claimed_at, **kwargs)
        conn.commit()
    if job is None:
        return "idle"
    try:
        if not api_key or not api_key.strip():
            raise FitError("missing_api_key", retryable=False)
        def reserve_and_commit():
            with conn_factory() as conn:
                sampled = []

                def reservation_clock():
                    value = clock()
                    sampled.append(value)
                    return value

                admitted = reserve_request(conn, entity_type='vacancy',
                                           entity_id=job.vacancy_id, now=reservation_clock)
                if not admitted:
                    now = clock()
                    accepted = store.defer_for_quota(conn, job, retry_at=next_midnight(now), now=now)
                    if accepted:
                        conn.commit()
                    else:
                        conn.rollback()
                    return None, accepted
                conn.commit()
                # Custom test doubles may not call the supplied clock; production
                # reserve_request samples it after acquiring the quota lock.
                return sampled[-1] if sampled else clock(), True

        reserved_at, accepted = reserve_and_commit()
        if reserved_at is None:
            return 'quota_exhausted' if accepted else 'lease_lost'
        # Keep an admission in the UTC day in which HTTP will start. A commit
        # or scheduler pause can itself cross midnight; retain the prior
        # conservative reservation and reserve again for the new day.
        while clock().astimezone(timezone.utc).date() != reserved_at.astimezone(timezone.utc).date():
            reserved_at, accepted = reserve_and_commit()
            if reserved_at is None:
                return 'quota_exhausted' if accepted else 'lease_lost'
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
