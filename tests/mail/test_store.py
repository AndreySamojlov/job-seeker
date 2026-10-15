import uuid

import pytest

from job_machine.db import migrate
from job_machine.mail import store


def _apply(conn):
    for m in migrate.pending(migrate.discover_migrations("db/migrations"),
                             migrate.applied_migrations(conn)):
        migrate.apply_migration(conn, m)
    conn.commit()


def _seed_application(conn, candidate_id="andrey-s", company="Acme", role="QA Lead"):
    canonical_url = f"https://example.com/{uuid.uuid4()}"
    with conn.cursor() as cur:
        cur.execute(
            "insert into vacancy (vacancy_id, company, title, canonical_url) "
            "values (gen_random_uuid(), %s, %s, %s) "
            "returning vacancy_id",
            (company, role, canonical_url))
        vacancy_id = cur.fetchone()[0]
        cur.execute(
            "insert into application (application_id, vacancy_id, candidate_id, state) "
            "values (gen_random_uuid(), %s, %s, 'submitted') "
            "returning application_id",
            (vacancy_id, candidate_id))
        return cur.fetchone()[0]


@pytest.mark.db
def test_cursor_roundtrip(db_schema):
    conn, _ = db_schema
    _apply(conn)
    assert store.get_cursor(conn, "workcockpit@gmail.com") == 0
    store.set_cursor(conn, "workcockpit@gmail.com", 42)
    conn.commit()
    assert store.get_cursor(conn, "workcockpit@gmail.com") == 42


@pytest.mark.db
def test_load_active_applications_returns_open_states(db_schema):
    conn, _ = db_schema
    _apply(conn)
    aid = _seed_application(conn)
    conn.commit()
    refs = store.load_active_applications(conn)
    assert any(r.application_id == str(aid) for r in refs)


@pytest.mark.db
def test_load_active_applications_excludes_applications_with_recorded_outcome(db_schema):
    conn, _ = db_schema
    _apply(conn)
    open_aid = _seed_application(conn, company="OpenCo", role="Open Role")
    resolved_aid = _seed_application(conn, company="ResolvedCo", role="Resolved Role")
    with conn.cursor() as cur:
        cur.execute(
            "update application set outcome_status='rejected', outcome_source='mail', "
            "outcome_confirmed_at=now() where application_id=%s", (resolved_aid,))
    conn.commit()
    refs = store.load_active_applications(conn)
    ids = {r.application_id for r in refs}
    assert str(open_aid) in ids
    assert str(resolved_aid) not in ids


@pytest.mark.db
def test_record_reply_outcome_writes_outcome_and_keeps_state(db_schema):
    conn, _ = db_schema
    _apply(conn)
    aid = _seed_application(conn)
    with conn.cursor() as cur:
        cur.execute("update application set state='submitted' where application_id=%s", (aid,))
    conn.commit()
    store.record_reply_outcome(conn, str(aid), "rejected")
    conn.commit()
    with conn.cursor() as cur:
        cur.execute("select state, outcome_status, outcome_source, outcome_confirmed_at "
                    "from application where application_id=%s", (aid,))
        state, outcome, source, confirmed_at = cur.fetchone()
        # Отказ работодателя не отменяет факт подачи — заявка остаётся submitted.
        assert state == "submitted"
        assert outcome == "rejected"
        assert source == "mail"
        assert confirmed_at is not None
        cur.execute(
            "select count(*) from event where entity_id=%s and event_type=%s",
            (aid, "application.rejected"))
        assert cur.fetchone()[0] == 1


@pytest.mark.db
def test_insert_inbound_email_is_idempotent_per_uid(db_schema):
    conn, _ = db_schema
    _apply(conn)
    conn.commit()
    store.insert_inbound_email(conn, mailbox="workcockpit@gmail.com", uid=7,
                               from_addr="hr@acme.com", subject="Update",
                               body_excerpt="...", candidate_id=None,
                               application_id=None, category="other",
                               confidence=0.1, status="needs_review")
    store.insert_inbound_email(conn, mailbox="workcockpit@gmail.com", uid=7,
                               from_addr="hr@acme.com", subject="Update",
                               body_excerpt="...", candidate_id=None,
                               application_id=None, category="other",
                               confidence=0.1, status="needs_review")
    conn.commit()
    with conn.cursor() as cur:
        cur.execute(
            "select count(*) from inbound_email where mailbox=%s and uid=%s",
            ("workcockpit@gmail.com", 7))
        assert cur.fetchone()[0] == 1
