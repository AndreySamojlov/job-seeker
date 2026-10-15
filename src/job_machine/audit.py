from psycopg.types.json import Jsonb

from job_machine.guards.base import GuardResult


def guard_result_payload(result: GuardResult) -> dict:
    """Сериализовать GuardResult в payload для audit-события."""
    return {
        "guard_name": result.guard_name,
        "stage": result.stage,
        "decision": result.decision.value,
        "next_action": result.next_action.value,
        "reason": result.reason,
        "payload_hash": result.payload_hash,
        "input_refs": result.input_refs,
        "normalizations": result.normalizations,
    }


def emit_event(conn, entity_type, entity_id, event_type, payload, trace_id=None):
    """Записать строку в таблицу event. Коммит — на стороне вызывающего.

    payload оборачивается в psycopg Jsonb для корректной адаптации в jsonb-колонку
    (psycopg3 типизирует str как text, а assignment-cast text->jsonb в Postgres нет).
    """
    with conn.cursor() as cur:
        cur.execute(
            "insert into event (entity_type, entity_id, event_type, payload_json, trace_id) "
            "values (%s, %s, %s, %s, %s)",
            (entity_type, entity_id, event_type, Jsonb(payload), trace_id),
        )


def emit_guard_event(conn, entity_type, entity_id, result: GuardResult, trace_id=None):
    """Записать guard-блок как событие event_type='guard.<name>'."""
    emit_event(
        conn, entity_type, entity_id,
        f"guard.{result.guard_name}", guard_result_payload(result), trace_id,
    )
