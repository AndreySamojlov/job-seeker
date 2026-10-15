import pytest

from job_machine import audit
from job_machine.guards.base import Decision, GuardResult, NextAction


def test_guard_result_payload_shape():
    r = GuardResult("G", "submit", Decision.STOP, next_action=NextAction.ASK_USER,
                    reason="why", payload_hash="PH", input_refs={"application_id": "a1"})
    p = audit.guard_result_payload(r)
    assert p == {
        "guard_name": "G",
        "stage": "submit",
        "decision": "stop",
        "next_action": "ask_user",
        "reason": "why",
        "payload_hash": "PH",
        "input_refs": {"application_id": "a1"},
        "normalizations": [],
    }


@pytest.mark.db
def test_emit_event_inserts_row(db_schema):
    import uuid
    from job_machine.db import migrate
    conn, schema = db_schema
    for m in migrate.pending(migrate.discover_migrations("db/migrations"),
                             migrate.applied_migrations(conn)):
        migrate.apply_migration(conn, m)

    eid = uuid.uuid4()
    audit.emit_event(conn, "application", eid, "state.approved__submitted", {"k": "v"})
    conn.commit()

    with conn.cursor() as cur:
        cur.execute("select entity_type, event_type, payload_json from event "
                    "where entity_id = %s", (eid,))
        row = cur.fetchone()
    assert row == ("application", "state.approved__submitted", {"k": "v"})


@pytest.mark.db
def test_emit_guard_event_uses_guard_prefix(db_schema):
    import uuid
    from job_machine.db import migrate
    conn, schema = db_schema
    for m in migrate.pending(migrate.discover_migrations("db/migrations"),
                             migrate.applied_migrations(conn)):
        migrate.apply_migration(conn, m)

    eid = uuid.uuid4()
    r = GuardResult("NoSubmitWithoutApproval", "submit", Decision.STOP,
                    next_action=NextAction.ASK_USER, reason="no token", payload_hash="PH")
    audit.emit_guard_event(conn, "application", eid, r)
    conn.commit()

    with conn.cursor() as cur:
        cur.execute("select event_type, payload_json from event "
                    "where entity_id = %s", (eid,))
        event_type, payload = cur.fetchone()
    assert event_type == "guard.NoSubmitWithoutApproval"
    # вся форма payload сохранена (jsonb читается как dict в psycopg3) — защита от дрейфа
    assert payload == audit.guard_result_payload(r)
