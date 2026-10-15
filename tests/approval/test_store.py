import uuid
from datetime import datetime, timedelta, timezone

import pytest

from job_machine.approval import store
from job_machine.db import migrate


def _apply(conn):
    for m in migrate.pending(migrate.discover_migrations("db/migrations"),
                             migrate.applied_migrations(conn)):
        migrate.apply_migration(conn, m)


def _seed_app(conn, state="pre_submit_ready", payload_hash="ph1"):
    with conn.cursor() as cur:
        cur.execute(
            "insert into vacancy (company, title, canonical_url, vacancy_status, state) "
            "values ('Acme','QA Lead','https://acme/a','triaged','triaged') "
            "returning vacancy_id")
        vid = cur.fetchone()[0]
        cur.execute(
            "insert into application (vacancy_id, candidate_id, verdict, package_status, state, "
            "payload_hash) "
            "values (%s,'andrey-s','apply','none',%s,%s) returning application_id",
            (vid, state, payload_hash))
        return str(cur.fetchone()[0])


def _seed_approval(conn, application_id, status="approved", payload_hash="ph1",
                   hours_until_expiry=24):
    expires = datetime.now(tz=timezone.utc) + timedelta(hours=hours_until_expiry)
    with conn.cursor() as cur:
        cur.execute(
            "insert into approval (application_id, approval_type, payload_hash, "
            "approval_status, approval_token, expires_at) "
            "values (%s,'submit',%s,%s,'tok1',%s) returning approval_id",
            (uuid.UUID(application_id), payload_hash, status, expires))
        return str(cur.fetchone()[0])


@pytest.mark.db
def test_pull_needs_approval_returns_pre_submit_ready_without_approval(db_schema):
    conn, _ = db_schema
    _apply(conn)
    aid = _seed_app(conn)
    conn.commit()
    rows = store.pull_needs_approval(conn, limit=10)
    assert len(rows) == 1
    assert rows[0]["application_id"] == aid
    assert rows[0]["payload_hash"] == "ph1"


@pytest.mark.db
def test_pull_needs_approval_excludes_already_has_approval(db_schema):
    conn, _ = db_schema
    _apply(conn)
    aid = _seed_app(conn)
    conn.commit()
    _seed_approval(conn, aid, status="pending")
    conn.commit()
    assert store.pull_needs_approval(conn, limit=10) == []


@pytest.mark.db
def test_create_approval_inserts_pending_record(db_schema):
    conn, _ = db_schema
    _apply(conn)
    aid = _seed_app(conn)
    conn.commit()
    expires = datetime.now(tz=timezone.utc) + timedelta(hours=24)
    approval_id = store.create_approval(conn, aid, "ph1", "secrettoken", expires)
    conn.commit()
    assert approval_id  # non-empty UUID string
    rec = store.load_by_application(conn, aid)
    assert rec is not None
    assert rec["approval_status"] == "pending"
    assert rec["approval_token"] == "secrettoken"
    assert rec["payload_hash"] == "ph1"


@pytest.mark.db
def test_approve_sets_approved_status(db_schema):
    conn, _ = db_schema
    _apply(conn)
    aid = _seed_app(conn)
    conn.commit()
    _seed_approval(conn, aid, status="pending")
    conn.commit()
    ok = store.approve(conn, aid)
    conn.commit()
    assert ok is True
    rec = store.load_by_application(conn, aid)
    assert rec["approval_status"] == "approved"
    assert rec.get("approved_at") is not None


@pytest.mark.db
def test_approve_returns_false_if_no_pending(db_schema):
    conn, _ = db_schema
    _apply(conn)
    aid = _seed_app(conn)
    conn.commit()
    assert store.approve(conn, aid) is False


@pytest.mark.db
def test_reject_sets_rejected_and_blocks_application(db_schema):
    conn, _ = db_schema
    _apply(conn)
    aid = _seed_app(conn)
    conn.commit()
    _seed_approval(conn, aid, status="pending")
    conn.commit()
    ok = store.reject(conn, aid, reason="doesn't meet requirements")
    conn.commit()
    assert ok is True
    rec = store.load_by_application(conn, aid)
    assert rec["approval_status"] == "rejected"
    with conn.cursor() as cur:
        cur.execute("select current_blocker from application where application_id=%s",
                    (uuid.UUID(aid),))
        assert cur.fetchone()[0] == "approval_rejected"


@pytest.mark.db
def test_approve_refuses_on_payload_drift(db_schema):
    conn, _ = db_schema
    _apply(conn)
    # Заявка одобрялась при ph1, но payload c тех пор изменился на ph2
    aid = _seed_app(conn, payload_hash="ph2")
    conn.commit()
    _seed_approval(conn, aid, status="pending", payload_hash="ph1")
    conn.commit()
    ok = store.approve(conn, aid)
    conn.commit()
    assert ok is False
    rec = store.load_by_application(conn, aid)
    assert rec["approval_status"] == "pending"  # НЕ approved
    # audit-событие payload_drift записано
    with conn.cursor() as cur:
        cur.execute(
            "select count(*) from event where event_type='application.approval_payload_drift'")
        assert cur.fetchone()[0] == 1


@pytest.mark.db
def test_approve_succeeds_when_payload_matches(db_schema):
    conn, _ = db_schema
    _apply(conn)
    aid = _seed_app(conn, payload_hash="ph1")
    conn.commit()
    _seed_approval(conn, aid, status="pending", payload_hash="ph1")
    conn.commit()
    ok = store.approve(conn, aid)
    conn.commit()
    assert ok is True
    rec = store.load_by_application(conn, aid)
    assert rec["approval_status"] == "approved"
    assert rec.get("approved_at") is not None


@pytest.mark.db
def test_approve_refuses_when_application_left_approvable_state(db_schema):
    """Заявка успела уйти в submit_blocked (напр. гонка с другим потоком) между
    request_approval и approve. approve() не должен бросать голое исключение —
    вызывающий (mcp/tools.py::approve_application) его не ловит — и не должен
    оставлять approval-строку 'approved' без соответствующего перехода
    application.state (submit-claim требует ОБА условия сразу)."""
    conn, _ = db_schema
    _apply(conn)
    aid = _seed_app(conn, state="submit_blocked")
    conn.commit()
    _seed_approval(conn, aid, status="pending")
    conn.commit()
    ok = store.approve(conn, aid)
    conn.commit()
    assert ok is False
    rec = store.load_by_application(conn, aid)
    assert rec["approval_status"] == "pending"  # откачено назад, НЕ "approved"
    with conn.cursor() as cur:
        cur.execute("select state from application where application_id=%s",
                    (uuid.UUID(aid),))
        assert cur.fetchone()[0] == "submit_blocked"  # не тронуто
        cur.execute(
            "select count(*) from event where event_type="
            "'application.approve_rejected_invalid_state'")
        assert cur.fetchone()[0] == 1


@pytest.mark.db
def test_load_by_application_none_if_no_approval(db_schema):
    conn, _ = db_schema
    _apply(conn)
    aid = _seed_app(conn)
    conn.commit()
    assert store.load_by_application(conn, aid) is None
