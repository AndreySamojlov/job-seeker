"""Fresh ATS verification and immutable provider snapshot preparation."""
from datetime import datetime, timezone

import httpx

from job_machine.discovery.sources import client_for
from job_machine.triage.htmltext import strip_html
from . import intake_store
from .models import ReadinessError
from .rubric import build_payload
from .store import ReadinessInput

INTAKE_LEASE_SECONDS = 360
MAX_JOB_TEXT_BYTES = 100_000


def default_client_factory(ats):
    return client_for(ats or "greenhouse")()


def build_readiness_payload(job_text):
    from cockpit_engine.rules import load_external_decision
    from .rules import READINESS_CATALOG, READINESS_CODE
    decision = load_external_decision(READINESS_CATALOG, READINESS_CODE)
    return build_payload(job_text, decision=decision)


def _ats_error(exc, *, during_check=False):
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        return ReadinessError("ats_not_found" if status == 404 else "ats_http_error",
                              status == 429 or status >= 500)
    if isinstance(exc, httpx.TransportError):
        return ReadinessError("ats_transport_error", True)
    if isinstance(exc, (ValueError, TypeError, AttributeError)):
        return ReadinessError("unsupported_ats" if during_check else "invalid_content")
    return ReadinessError("ats_check_error" if during_check else "ats_fetch_error", True)


def run_once(conn_factory, *, client_factory=default_client_factory,
             payload_builder=None,
             max_attempts=intake_store.MAX_ATTEMPTS,
             clock=lambda: datetime.now(timezone.utc)):
    """Process one intake item; only live-check and fetch failures can retry ATS."""
    with conn_factory() as conn:
        job = intake_store.claim_due(conn, now=clock(), lease_seconds=INTAKE_LEASE_SECONDS,
                                     max_attempts=max_attempts)
        conn.commit()
    if job is None:
        return "idle"
    payload_builder = payload_builder or build_readiness_payload

    try:
        with conn_factory() as conn:
            existing = conn.execute(
                "select exists (select 1 from remote_work_readiness_job where vacancy_id=%s)",
                (job.vacancy_id,),
            ).fetchone()[0]
        if existing:
            with conn_factory() as conn:
                accepted = intake_store.finish_existing(conn, job, now=clock())
                if accepted:
                    conn.commit()
                else:
                    conn.rollback()
            return "existing" if accepted else "lease_lost"

        with conn_factory() as conn:
            vacancy = conn.execute(
                "select ats_family,source_url,vacancy_status,work_mode from vacancy where vacancy_id=%s",
                (job.vacancy_id,),
            ).fetchone()
        if vacancy is None:
            return _finish_blocked(conn_factory, job, "vacancy_missing", clock)
        ats, url, vacancy_status, work_mode = vacancy
        if vacancy_status != "verified" or work_mode == "onsite":
            return _finish_blocked(conn_factory, job, "not_eligible", clock)
        if not isinstance(url, str) or not url.strip():
            return _finish_blocked(conn_factory, job, "invalid_source_url", clock)

        client = None
        stage = "client"
        try:
            client = client_factory(ats or "greenhouse")
            stage = "check"
            check = client.check_job(url)
            if check == "gone":
                return _finish_gone(conn_factory, job, clock)
            if check != "live":
                return _fail(conn_factory, job, ReadinessError("verification_unknown", True), clock,
                             max_attempts=max_attempts)

            stage = "fetch"
            content = client.fetch_content(url)
            if content is None:
                return _finish_blocked(conn_factory, job, "no_content", clock)
            if not isinstance(content, str):
                return _finish_blocked(conn_factory, job, "invalid_content", clock)
            if len(content.encode("utf-8")) > MAX_JOB_TEXT_BYTES:
                return _finish_blocked(conn_factory, job, "input_too_large", clock)
            text = strip_html(content).strip()
            if not text:
                return _finish_blocked(conn_factory, job, "no_content", clock)
            if len(text.encode("utf-8")) > MAX_JOB_TEXT_BYTES:
                return _finish_blocked(conn_factory, job, "input_too_large", clock)
            stage = "payload"
            payload = payload_builder(text)
        except ReadinessError as error:
            return _fail(conn_factory, job, error, clock, max_attempts=max_attempts)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404 and stage in {"check", "fetch"}:
                return _finish_gone(conn_factory, job, clock)
            return _fail(conn_factory, job, _ats_error(exc), clock, max_attempts=max_attempts)
        except httpx.TransportError as exc:
            return _fail(conn_factory, job, _ats_error(exc), clock, max_attempts=max_attempts)
        except (ValueError, TypeError, AttributeError) as exc:
            return _finish_blocked(conn_factory, job, _ats_error(exc, during_check=stage in {"client", "check"}), clock)
        except Exception:
            return _fail(conn_factory, job, ReadinessError("ats_operation_failed", True), clock,
                         max_attempts=max_attempts)
        finally:
            if client is not None:
                try:
                    client.close()
                except Exception:
                    pass

        readiness_input = ReadinessInput(job.vacancy_id, text, work_mode or "unknown")
        with conn_factory() as conn:
            result = intake_store.finish_with_snapshot(
                conn, job, readiness_input, payload, now=clock())
            if result in {True, "prepared", "existing", "blocked"}:
                conn.commit()
            else:
                conn.rollback()
        if result == "blocked":
            return "blocked"
        return "prepared" if result in {True, "prepared", "existing"} else "lease_lost"
    except Exception:
        return _fail(conn_factory, job, ReadinessError("preparation_failed", True), clock,
                     max_attempts=max_attempts)


def _fail(conn_factory, job, error, clock, *, max_attempts=intake_store.MAX_ATTEMPTS):
    with conn_factory() as conn:
        accepted = intake_store.fail(conn, job, error, now=clock(), max_attempts=max_attempts)
        if accepted:
            conn.commit()
        else:
            conn.rollback()
    return ("retry_wait" if error.retryable else "blocked") if accepted else "lease_lost"


def _finish_blocked(conn_factory, job, code, clock):
    with conn_factory() as conn:
        accepted = intake_store.finish_blocked(conn, job, code, now=clock())
        if accepted:
            conn.commit()
        else:
            conn.rollback()
    return "blocked" if accepted else "lease_lost"


def _finish_gone(conn_factory, job, clock):
    with conn_factory() as conn:
        accepted = intake_store.finish_gone(conn, job, now=clock())
        if accepted:
            conn.commit()
        else:
            conn.rollback()
    return "gone" if accepted else "lease_lost"
