"""Авто-конвейер: discovery → verify → triage (LLM) → resume (LLM) → package → fill.

Принцип: детерминированные стадии (discovery/verify/package/fill) делегируются
существующим сервисам. LLM-стадии (triage/resume) встроены здесь с per-item
изоляцией и rollback.

Дискавери — мульти-сорс через реестр среза A:
run_discovery_multi(conn, sources). Источники берутся из config/sources.json
(load_sources), либо из переданного sources, либо — для обратной совместимости
CLI — из boards (трактуются как greenhouse-доски).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from job_machine.cloud.store import load_cloud
from job_machine.discovery import service as discovery_service
from job_machine.discovery.sources import SourceSpec, load_sources
from job_machine.fill import service as fill_service
from job_machine.fit import preparation as fit_preparation
from job_machine.fit.preparation import default_client_factory as _default_fit_client_factory
from job_machine.fit import worker as fit_worker
from job_machine.mcp import store as mcp_store
from job_machine.package import service as package_service
from job_machine.resume import selector, service as resume_service, store as resume_store
from job_machine.remote_readiness import intake_store as readiness_intake_store
from job_machine.remote_readiness import preparation as readiness_preparation
from job_machine.remote_readiness import worker as readiness_worker
from job_machine.remote_readiness import control_store as readiness_control_store
from job_machine.remote_readiness.settings import ReadinessSettings
from job_machine.triage import service as triage_service

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Summary dataclass
# ---------------------------------------------------------------------------

@dataclass
class AutoCycleSummary:
    inserted: int = 0
    verified: int = 0
    triaged: int = 0
    triage_skipped: int = 0
    triage_errors: int = 0
    phrased: int = 0
    resume_errors: int = 0
    packaged: int = 0
    pre_submit_ready: int = 0
    fit_prepared: int = 0
    fit_prepare_retry: int = 0
    fit_prepare_blocked: int = 0
    fit_completed: int = 0
    fit_retry: int = 0
    fit_blocked: int = 0
    readiness_enqueued: int = 0
    readiness_existing: int = 0
    readiness_prepared: int = 0
    readiness_prepare_retry: int = 0
    readiness_prepare_blocked: int = 0
    readiness_gone: int = 0
    readiness_completed: int = 0
    readiness_retry: int = 0
    readiness_blocked: int = 0
    readiness_enabled: bool = False
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Thin wrappers (monkeypatch-friendly для тестов)
# ---------------------------------------------------------------------------

def _pull_needs_resume(conn, limit: int) -> list[dict]:
    return resume_store.pull_needs_resume(conn, limit)


def _apply_one_resume(conn, pdf_client, base_dir: str, phrasing) -> Any:
    return resume_service.apply_phrasing(conn, pdf_client, base_dir, phrasing)


def _readiness_settings_from_env():
    return ReadinessSettings.from_env()


# ---------------------------------------------------------------------------
# Stage helpers
# ---------------------------------------------------------------------------

def _stage(summary: AutoCycleSummary, name: str, fn) -> None:
    """Запустить стадию, падение → summary.errors."""
    try:
        fn()
    except Exception as exc:  # noqa: BLE001
        log.exception("Ошибка в стадии %s", name)
        summary.errors.append(f"{name}: {exc}")


def _safe_stage(summary: AutoCycleSummary, name: str, fn) -> None:
    """Fit-stage errors can carry snapshots/DSNs; expose only a fixed code."""
    try:
        fn()
    except Exception:  # noqa: BLE001
        log.error("Ошибка в стадии %s (operation_failed)", name)
        summary.errors.append(f"{name}: operation_failed")


# ---------------------------------------------------------------------------
# LLM-стадии
# ---------------------------------------------------------------------------

def _run_triage(conn, llm, triage_client, summary: AutoCycleSummary, limit: int) -> None:
    """Пер-кандидатный: для каждого активного кандидата — детерминированный pull →
    per-item LLM verdict → apply. Per-item изоляция (в рамках кандидата)."""
    for candidate in mcp_store.list_candidates(conn):
        cid = candidate["candidate_id"]
        pull_summary = triage_service.build_triage_inputs(conn, triage_client, cid, limit)
        for inp in pull_summary.inputs:
            try:
                verdict = llm.triage_verdict(inp)
                # Доверенный id: всегда берём из детерминированного inp (§3)
                verdict.vacancy_id = inp.vacancy_id
                route = triage_service.apply_triage(conn, verdict, cid,
                                                    pull_summary.claims_version)
                if route == "skipped":
                    summary.triage_skipped += 1
                else:
                    summary.triaged += 1
            except Exception as exc:  # noqa: BLE001
                log.exception("Ошибка triage для вакансии %s (candidate %s)",
                             inp.vacancy_id, cid)
                conn.rollback()
                summary.triage_errors += 1
                summary.errors.append(f"triage[{cid}/{inp.vacancy_id}]: {exc}")


def _run_resume(conn, llm, pdf_client, base_dir: str, summary: AutoCycleSummary, limit: int) -> None:
    """Per-item: pull_needs_resume → build_selection → phrasing_request → llm → apply."""
    rows = _pull_needs_resume(conn, limit)
    for row in rows:
        try:
            cloud = load_cloud(conn, row["candidate_id"])
            sel = selector.build_selection(
                row["application_id"],
                row["role"],
                row["hard_requirements"],
                cloud,
                candidate_name=row.get("candidate_name", ""),
                candidate_id=row["candidate_id"],
            )
            req = selector.phrasing_request(sel)
            phrasing = llm.resume_phrasing(req)
            # Привязать application_id из row (доверенный источник, не LLM)
            phrasing.application_id = row["application_id"]
            _apply_one_resume(conn, pdf_client, base_dir, phrasing)
            summary.phrased += 1
        except Exception as exc:  # noqa: BLE001
            log.exception("Ошибка resume для заявки %s", row.get("application_id"))
            conn.rollback()
            summary.resume_errors += 1
            summary.errors.append(f"resume[{row.get('application_id')}]: {exc}")


# ---------------------------------------------------------------------------
# Главная функция
# ---------------------------------------------------------------------------

def run_auto_cycle(
    conn,
    *,
    llm,
    browser,
    pdf,
    discovery_client,
    boards: list[str] | None = None,
    sources: list[SourceSpec] | None = None,
    base_dir: str = "applications",
    limit: int = 10,
    conn_factory=None,
    fit_client=None,
    fit_api_key: str = "",
    fit_client_factory=None,
    fit_answer_allowlist=(),
    readiness_client=None,
    readiness_api_key: str | None = None,
    readiness_client_factory=None,
) -> AutoCycleSummary:
    """Прогнать полный автономный конвейер с LLM-стадиями triage и resume.

    Порядок стадий: discovery → verify → RWR intake/preparation/Jev → fit preparation/Jev
    → triage → resume → package → fill.
    Детерминированные стадии делегируются соответствующим сервисам.
    LLM-стадии выполняются per-item с изоляцией падения и rollback.

    Источники дискавери (приоритет): явный ``sources`` → ``boards`` (как
    greenhouse-доски, для обратной совместимости CLI) → ``config/sources.json``.
    Discovery идёт через run_discovery_multi (мульти-ATS). verify/triage
    по-прежнему используют ``discovery_client``.
    """
    summary = AutoCycleSummary()

    if sources is not None:
        specs = sources
    elif boards:
        specs = [SourceSpec(ats="greenhouse", token=b) for b in boards]
    else:
        specs = load_sources()

    # --- Discovery (мульти-сорс) ---
    def _disc():
        result = discovery_service.run_discovery_multi(conn, specs)
        summary.inserted = getattr(result, "inserted", 0)

    _stage(summary, "discover", _disc)

    # --- Verify ---
    def _ver():
        result = discovery_service.run_verify(conn, discovery_client, limit)
        summary.verified = getattr(result, "verified", 0)

    _stage(summary, "verify", _ver)

    readiness_settings = None
    readiness_intake_limit = readiness_jev_limit = 0
    readiness_enabled = False
    if limit > 0:
        try:
            readiness_settings = _readiness_settings_from_env()
            readiness_intake_limit = min(limit, readiness_settings.intake_batch_limit)
            readiness_jev_limit = min(limit, readiness_settings.jev_batch_limit)
            if readiness_settings.enabled:
                if conn_factory is None:
                    raise ValueError("readiness control requires conn_factory")
                with conn_factory() as control_conn:
                    readiness_enabled = readiness_control_store.is_enabled(control_conn)
        except Exception:
            # Fail closed. Never expose settings exceptions, which could include env data.
            summary.errors.append("readiness_control: operation_failed")
            readiness_enabled = False
    summary.readiness_enabled = readiness_enabled

    def _readiness_still_enabled() -> bool:
        """Re-read the persistent circuit breaker at every RWR boundary.

        The initial read is only a cycle-level snapshot. An operator may
        disable RWR while discovery or another bounded item is running.
        """
        nonlocal readiness_enabled
        if not readiness_enabled or readiness_settings is None or not readiness_settings.enabled:
            return False
        if conn_factory is None:
            readiness_enabled = False
            summary.readiness_enabled = False
            return False
        try:
            with conn_factory() as control_conn:
                enabled_now = readiness_control_store.is_enabled(control_conn)
        except Exception:
            # Fail closed on a lost/unknown control state.
            summary.errors.append("readiness_control: operation_failed")
            enabled_now = False
        if not enabled_now:
            readiness_enabled = False
            summary.readiness_enabled = False
        return enabled_now

    # Readiness assignment has its own bounded intake queue. Existing verified
    # rows receive a fresh ATS check in preparation before any snapshot exists.
    def _readiness_enqueue():
        if readiness_intake_limit <= 0 or not _readiness_still_enabled():
            return
        summary.readiness_enqueued = readiness_intake_store.enqueue_verified(
            conn, limit=readiness_intake_limit)
        conn.commit()

    _safe_stage(summary, "readiness_enqueue", _readiness_enqueue)

    def _readiness_prepare():
        if readiness_intake_limit <= 0 or not _readiness_still_enabled():
            return
        if conn_factory is None:
            raise ValueError("readiness preparation requires conn_factory")
        for _ in range(readiness_intake_limit):
            # Recheck before each claim/ATS unit. A disable observed after one
            # item prevents claiming the next one in this cycle.
            if not _readiness_still_enabled():
                break
            outcome = readiness_preparation.run_once(
                conn_factory,
                client_factory=readiness_client_factory or readiness_preparation.default_client_factory,
                max_attempts=readiness_settings.max_attempts,
                clock=lambda: datetime.now(timezone.utc),
            )
            if outcome == "idle":
                break
            if outcome == "prepared":
                summary.readiness_prepared += 1
            elif outcome == "existing":
                summary.readiness_existing += 1
            elif outcome == "retry_wait":
                summary.readiness_prepare_retry += 1
            elif outcome == "blocked":
                summary.readiness_prepare_blocked += 1
            elif outcome == "gone":
                summary.readiness_gone += 1
            elif outcome == "lease_lost":
                continue
            else:
                raise ValueError("invalid readiness preparation outcome")

    _safe_stage(summary, "readiness_prepare", _readiness_prepare)

    def _readiness_evaluate():
        if readiness_jev_limit <= 0 or not _readiness_still_enabled():
            return
        client = readiness_client if readiness_client is not None else fit_client
        api_key = fit_api_key if readiness_api_key is None else readiness_api_key
        if conn_factory is None:
            raise ValueError("readiness evaluation requires conn_factory")
        if client is None:
            raise ValueError("readiness evaluation requires readiness_client")
        for _ in range(readiness_jev_limit):
            # Recheck before every claim/Jev unit, not only once per cycle.
            if not _readiness_still_enabled():
                break
            outcome = readiness_worker.run_once(
                conn_factory, client=client, api_key=api_key,
                max_attempts=readiness_settings.max_attempts,
                timeout_seconds=readiness_settings.request_timeout_seconds,
                clock=lambda: datetime.now(timezone.utc),
            )
            if outcome == "idle":
                break
            if outcome == "completed":
                summary.readiness_completed += 1
            elif outcome == "retry_wait":
                summary.readiness_retry += 1
            elif outcome == "blocked":
                summary.readiness_blocked += 1
            elif outcome == "lease_lost":
                continue
            else:
                raise ValueError("invalid readiness Jev outcome")

    _safe_stage(summary, "readiness_jev", _readiness_evaluate)

    # Durable queues are drained every cycle, including work left by earlier
    # cycles. Each queue has an independent batch bound and stage isolation.
    def _fit_prepare():
        if conn_factory is None:
            raise ValueError("fit preparation requires conn_factory")
        factory = fit_client_factory or _default_fit_client_factory
        for _ in range(max(0, limit)):
            outcome = fit_preparation.run_once(
                conn_factory, client_factory=factory,
                answer_allowlist=fit_answer_allowlist,
            )
            if outcome == "idle":
                break
            if outcome == "prepared":
                summary.fit_prepared += 1
            elif outcome == "retry_wait":
                summary.fit_prepare_retry += 1
            elif outcome == "blocked":
                summary.fit_prepare_blocked += 1
            elif outcome == "lease_lost":
                continue
            else:
                raise ValueError("invalid fit preparation outcome")

    _safe_stage(summary, "fit_prepare", _fit_prepare)

    def _fit_evaluate():
        if conn_factory is None:
            raise ValueError("fit evaluation requires conn_factory")
        if fit_client is None:
            raise ValueError("fit evaluation requires fit_client")
        for _ in range(max(0, limit)):
            outcome = fit_worker.run_once(
                conn_factory, client=fit_client, api_key=fit_api_key,
                clock=lambda: datetime.now(timezone.utc),
            )
            if outcome == "idle":
                break
            if outcome == "completed":
                summary.fit_completed += 1
            elif outcome == "retry_wait":
                summary.fit_retry += 1
            elif outcome == "blocked":
                summary.fit_blocked += 1
            elif outcome == "lease_lost":
                continue
            else:
                raise ValueError("invalid Jev outcome")

    _safe_stage(summary, "fit_jev", _fit_evaluate)

    # --- Triage (LLM) ---
    def _triage():
        _run_triage(conn, llm, discovery_client, summary, limit)

    _stage(summary, "triage", _triage)

    # --- Resume (LLM) ---
    def _resume():
        _run_resume(conn, llm, pdf, base_dir, summary, limit)

    _stage(summary, "resume", _resume)

    # --- Package ---
    def _pack():
        result = package_service.run_package_build(conn, base_dir, limit)
        summary.packaged = result if isinstance(result, int) else getattr(result, "built", 0)

    _stage(summary, "package", _pack)

    # --- Fill ---
    def _fill():
        result = fill_service.run_fill(conn, browser, limit)
        summary.pre_submit_ready = getattr(result, "pre_submit_ready", 0)

    _stage(summary, "fill", _fill)

    return summary
