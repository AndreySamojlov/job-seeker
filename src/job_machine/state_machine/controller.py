from dataclasses import dataclass
from enum import Enum

from job_machine import audit
from job_machine.guards.base import Decision, GuardResult
from job_machine.guards import registry
from job_machine.state_machine.transitions import ALLOWED, GUARDS


@dataclass
class TransitionResult:
    ok: bool
    entity_type: str
    entity_id: str
    from_state: object
    to_state: object
    blocked_by: GuardResult | None = None


def _state_value(state) -> str:
    return state.value if isinstance(state, Enum) else str(state)


def attempt_transition(
    entity_type,
    entity_id,
    current,
    target,
    ctx,
    *,
    state_writer,
    audit_emitter,
    guard_resolver=registry.get,
) -> TransitionResult:
    """Авторизовать и выполнить переход current -> target.

    state_writer(entity_type, entity_id, *, state=None, current_blocker=...) —
      пишет состояние/блокер; на блоке передаётся только current_blocker.
    audit_emitter(entity_type, entity_id, event_type, payload, trace_id=None) —
      пишет событие.
    guard_resolver(name) -> Guard — резолвит guard по имени (по умолчанию из реестра).
    """
    trace_id = getattr(ctx, "trace_id", None)

    # 1. Структурная проверка легальности перехода.
    # Нелегальный переход — это ошибка вызова (неверный target), а не операционный
    # блокер сущности, поэтому пишем audit-событие, но НЕ трогаем current_blocker
    # (он зарезервирован под guard-блоки легальных переходов: captcha, expiry и т.п.).
    if target not in ALLOWED.get((entity_type, current), set()):
        blocked = GuardResult(
            "transition", "state_machine", Decision.STOP,
            reason=f"illegal transition {_state_value(current)} -> {_state_value(target)}",
        )
        audit_emitter(entity_type, entity_id, "guard.transition",
                      audit.guard_result_payload(blocked), trace_id)
        return TransitionResult(False, entity_type, entity_id, current, target, blocked)

    # 2. Прогон required-guards по порядку.
    for name in GUARDS.get((entity_type, current, target), []):
        result = guard_resolver(name).check(ctx)
        if result.decision is not Decision.CONTINUE:
            audit_emitter(
                entity_type, entity_id, f"guard.{result.guard_name}",
                audit.guard_result_payload(result), trace_id,
            )
            state_writer(entity_type, entity_id, current_blocker=result.reason)
            return TransitionResult(False, entity_type, entity_id, current, target, result)

    # 3. Все guards CONTINUE — фиксируем переход.
    state_writer(entity_type, entity_id, state=target, current_blocker=None)
    audit_emitter(
        entity_type, entity_id,
        f"state.{_state_value(current)}__{_state_value(target)}", {}, trace_id,
    )
    return TransitionResult(True, entity_type, entity_id, current, target)
