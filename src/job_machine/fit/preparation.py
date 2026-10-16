"""Durable ATS preparation. No payload or exception diagnostics are logged."""
from datetime import datetime, timezone
import httpx
from pydantic import ValidationError
from job_machine.discovery.sources import client_for
from job_machine.triage.htmltext import strip_html
from .models import FitError
from .facts import build_fit_input
from .store import create_job
from . import preparation_store as store

PREPARATION_LEASE_SECONDS = 360


def default_client_factory(ats):
    return client_for(ats or 'greenhouse')()


def fetch_text(ats, url, client_factory=default_client_factory):
    client = None
    try:
        client = client_factory(ats or 'greenhouse')
        content = client.fetch_content(url)
        if content is None:
            raise FitError('no_content')
        if not isinstance(content, str):
            raise FitError('invalid_content')
        if len(content.encode('utf-8')) > 100_000:
            raise FitError('input_too_large')
        text = strip_html(content).strip()
        if not text:
            raise FitError('no_content')
        return text
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        raise FitError('ats_not_found' if status == 404 else 'ats_http_error', status == 429 or status >= 500) from None
    except httpx.TransportError:
        raise FitError('ats_transport_error', True) from None
    except (ValueError, TypeError, AttributeError):
        raise FitError('invalid_content') from None
    finally:
        if client is not None:
            getattr(client, 'close', lambda: None)()


def run_once(conn_factory, *, client_factory=default_client_factory, answer_allowlist=(), clock=lambda: datetime.now(timezone.utc)):
    with conn_factory() as conn:
        job = store.claim_due(conn, now=clock(), lease_seconds=PREPARATION_LEASE_SECONDS)
        conn.commit()
    if job is None:
        return 'idle'
    try:
        text = job.job_text
        if text is None:
            with conn_factory() as conn:
                row = conn.execute('select ats_family,source_url from vacancy where vacancy_id=%s', (job.vacancy_id,)).fetchone()
            if row is None:
                raise FitError('vacancy_missing')
            text = fetch_text(*row, client_factory)
            with conn_factory() as conn:
                if not store.save_text(conn, job, text, now=clock()):
                    return 'lease_lost'
                conn.commit()
        with conn_factory() as conn:
            children = store.due_children(conn, job, now=clock())
        for candidate_id in children:
            with conn_factory() as conn:
                try:
                    if not store.renew_lease(conn, job, now=clock(), lease_seconds=PREPARATION_LEASE_SECONDS):
                        return 'lease_lost'
                    value = build_fit_input(conn, candidate_id=candidate_id, vacancy_id=job.vacancy_id, job_text=text, answer_allowlist=answer_allowlist)
                    create_job(conn, value)
                    if not store.prepare_child(conn, job, candidate_id, now=clock()):
                        return 'lease_lost'
                    conn.commit()
                except Exception as exc:
                    conn.rollback()
                    if isinstance(exc, FitError):
                        error = exc
                    elif isinstance(exc, ValidationError):
                        error = FitError('invalid_candidate_facts', False)
                    else:
                        error = FitError('facts_failed', True)
                    if not store.fail_child(conn, job, candidate_id, error, now=clock()):
                        return 'lease_lost'
                    conn.commit()
        with conn_factory() as conn:
            result = store.finish(conn, job, now=clock())
            conn.commit()
            return result
    except Exception as exc:
        error = exc if isinstance(exc, FitError) else FitError('preparation_failed', True)
        with conn_factory() as conn:
            accepted = store.fail(conn, job, error, now=clock())
            conn.commit()
        return ('retry_wait' if error.retryable else 'blocked') if accepted else 'lease_lost'
