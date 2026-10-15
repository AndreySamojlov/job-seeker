"""[SAFETY] Submit gate: загрузить approval + application → GuardContext → 3 submit-гарда.

Вызывается submit-воркером ДО открытия браузерной сессии. Возврат None = все гарды
пропускают (CONTINUE). Первый STOP-результат — блокируем заявку и аудитируем.
"""
import uuid
from datetime import datetime

from job_machine.approval.store import load_by_application
from job_machine.guards.approval import (
    NoResumeUploadWithoutHashMatch,
    NoSubmitAfterApprovalExpiry,
    NoSubmitIfPayloadHashChanged,
    NoSubmitWithoutApproval,
)
from job_machine.guards.base import Decision, GuardResult, NextAction
from job_machine.guards.context import GuardContext

_SUBMIT_GUARDS = (
    NoSubmitWithoutApproval(),
    NoSubmitIfPayloadHashChanged(),
    NoSubmitAfterApprovalExpiry(),
)


def _load_application(conn, application_id: str) -> dict | None:
    with conn.cursor() as cur:
        cur.execute(
            "select application_id, payload_hash from application "
            "where application_id=%s",
            (uuid.UUID(application_id),))
        row = cur.fetchone()
    if row is None:
        return None
    return {"application_id": str(row[0]), "payload_hash": row[1]}


def check_submit_gate(conn, application_id: str,
                      now: datetime) -> GuardResult | None:
    """Прогнать 3 submit-гарда; вернуть первый STOP или None если все CONTINUE."""
    try:
        uuid.UUID(application_id)
    except (ValueError, TypeError, AttributeError):
        # Fail-closed: кривой/None id не должен ронять сам гейт голым исключением —
        # возвращаем STOP. Best-effort defense-in-depth: в реальном submit-потоке id
        # приходит из БД (всегда валиден), а кривой id падает раньше в claim_application.
        # NB: downstream record_guard_block тоже парсит id, поэтому audit-событие для
        # синтетически-кривого id не гарантируется — это не §7-контракт, а ранний STOP.
        return GuardResult(
            "ValidApplicationId", "submit", Decision.STOP,
            next_action=NextAction.ESCALATE_TO_DEBUG,
            reason=f"invalid application_id: {application_id!r}",
            input_refs={"application_id": application_id},
        )
    app_dict = _load_application(conn, application_id)
    approval_dict = load_by_application(conn, application_id)
    ctx = GuardContext(
        application=app_dict,
        approval=approval_dict,
        now=now,
    )
    for guard in _SUBMIT_GUARDS:
        result = guard.check(ctx)
        if not result.ok:
            return result
    return None


def check_resume_hash_gate(resume_artifact: dict,
                           disclosed_resume_hash: str | None) -> GuardResult | None:
    """Re-verify resume hash before submit (§3 resume safety — mirrors fill/gate.py)."""
    ctx = GuardContext(
        resume_artifact=resume_artifact,
        disclosed_resume_hash=disclosed_resume_hash,
    )
    g = NoResumeUploadWithoutHashMatch().check(ctx)
    return None if g.ok else g
