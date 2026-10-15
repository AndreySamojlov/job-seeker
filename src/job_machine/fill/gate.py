"""Контур безопасности fill-стадии: гарды раскрытия + fail-closed блокеры inspect.

check_fill_gate запускает уже смёрдженные fill-стадийные гарды по построенному контексту.
inspect_block_label закрывает координационный шов (ADR 2026-06-23 control-layer, п. b):
любой НЕ-None ярлык воркера трактуется как STOP, неизвестные ярлыки тоже — никакого
конвертирования в булев dict, где неизвестный ключ молча стал бы False → CONTINUE.
"""

from job_machine.guards.approval import (
    NoFillBeforeDisclosedSummary,
    NoResumeUploadWithoutHashMatch,
)
from job_machine.guards.context import GuardContext

_FILL_GUARDS = (NoFillBeforeDisclosedSummary(), NoResumeUploadWithoutHashMatch())


def check_fill_gate(summary_artifacts, resume_artifact, disclosed_resume_hash):
    """Вернуть первый STOP-GuardResult или None, если все гарды пропускают."""
    ctx = GuardContext(
        summary_artifacts=summary_artifacts or [],
        resume_artifact=resume_artifact,
        disclosed_resume_hash=disclosed_resume_hash,
    )
    for guard in _FILL_GUARDS:
        result = guard.check(ctx)
        if not result.ok:
            return result
    return None


def inspect_block_label(blocker):
    """Fail-closed: любой не-None ярлык → STOP (возвращаем его как current_blocker)."""
    if blocker is None:
        return None
    return blocker
