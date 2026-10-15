import json

import pytest

from job_machine.db import migrate
from job_machine.telegram_sourcing import store
from job_machine.telegram_sourcing.parser import RawMessage


def _apply_migrations(conn):
    for m in migrate.pending(migrate.discover_migrations("db/migrations"),
                             migrate.applied_migrations(conn)):
        migrate.apply_migration(conn, m)


def _seed_candidate_with_roles(conn, candidate_id, roles):
    with conn.cursor() as cur:
        cur.execute(
            "insert into candidate (candidate_id, name) values (%s, %s) "
            "on conflict (candidate_id) do nothing", (candidate_id, candidate_id))
        cur.execute(
            "insert into search_profile (candidate_id, roles) values (%s, %s::jsonb) "
            "on conflict (candidate_id) do update set roles=excluded.roles",
            (candidate_id, json.dumps(roles)))


def _msg(msg_id=1, text="QA Engineer remote"):
    return RawMessage(channel="forallqa", message_id=msg_id,
                      permalink=f"https://t.me/forallqa/{msg_id}",
                      posted_at="2026-07-15T10:00:00+00:00", text=text)


@pytest.mark.db
def test_upsert_lead_inserts_new_row(db_schema):
    conn, _ = db_schema
    _apply_migrations(conn)
    assert store.upsert_lead(conn, _msg()) is True
    with conn.cursor() as cur:
        cur.execute("select channel, message_id from telegram_lead")
        assert cur.fetchone() == ("forallqa", 1)


@pytest.mark.db
def test_upsert_lead_dedups_same_channel_and_message_id(db_schema):
    conn, _ = db_schema
    _apply_migrations(conn)
    assert store.upsert_lead(conn, _msg(1, "first")) is True
    assert store.upsert_lead(conn, _msg(1, "duplicate")) is False
    with conn.cursor() as cur:
        cur.execute("select count(*) from telegram_lead")
        assert cur.fetchone()[0] == 1


@pytest.mark.db
def test_apply_keyword_match_flags_matching_new_leads(db_schema):
    conn, _ = db_schema
    _apply_migrations(conn)
    _seed_candidate_with_roles(conn, "andrey-s", ["QA Lead"])
    store.upsert_lead(conn, _msg(1, "Looking for a QA Lead, remote Europe"))
    store.upsert_lead(conn, _msg(2, "Senior Backend Engineer, onsite Berlin"))
    updated = store.apply_keyword_match(conn)
    assert updated == 1
    with conn.cursor() as cur:
        cur.execute("select message_id, keyword_match from telegram_lead order by message_id")
        assert cur.fetchall() == [(1, True), (2, False)]


@pytest.mark.db
def test_apply_keyword_match_noop_without_active_candidates(db_schema):
    conn, _ = db_schema
    _apply_migrations(conn)
    # migrations 0006/0010 seed a default 'andrey-s' candidate with roles — deactivate
    # it explicitly to construct the true zero-active-candidates state this test needs.
    with conn.cursor() as cur:
        cur.execute("update candidate set active = false")
    store.upsert_lead(conn, _msg())
    assert store.apply_keyword_match(conn) == 0


@pytest.mark.db
def test_load_new_for_triage_prioritizes_keyword_match(db_schema):
    conn, _ = db_schema
    _apply_migrations(conn)
    _seed_candidate_with_roles(conn, "andrey-s", ["QA Lead"])
    store.upsert_lead(conn, _msg(1, "Backend Engineer onsite"))
    store.upsert_lead(conn, _msg(2, "QA Lead remote"))
    store.apply_keyword_match(conn)
    leads = store.load_new_for_triage(conn, candidate_id="andrey-s", limit=10)
    assert [lead["channel"] + str(lead["keyword_match"]) for lead in leads][0].endswith("True")
    assert len(leads) == 2


@pytest.mark.db
def test_load_new_for_triage_is_scoped_per_candidate(db_schema):
    conn, _ = db_schema
    _apply_migrations(conn)
    _seed_candidate_with_roles(conn, "andrey-s", ["QA Lead"])
    _seed_candidate_with_roles(conn, "daria-b", ["QA Engineer"])
    store.upsert_lead(conn, _msg())
    [lead] = store.load_new_for_triage(conn, candidate_id="andrey-s", limit=10)

    store.apply_triage_verdict(conn, lead["lead_id"], "andrey-s", False)

    assert store.load_new_for_triage(conn, candidate_id="andrey-s", limit=10) == []
    still_new = store.load_new_for_triage(conn, candidate_id="daria-b", limit=10)
    assert len(still_new) == 1
    assert still_new[0]["lead_id"] == lead["lead_id"]


@pytest.mark.db
def test_apply_triage_verdict_upserts_per_candidate_row(db_schema):
    conn, _ = db_schema
    _apply_migrations(conn)
    _seed_candidate_with_roles(conn, "andrey-s", ["QA Lead"])
    store.upsert_lead(conn, _msg())
    [lead] = store.load_new_for_triage(conn, candidate_id="andrey-s", limit=10)

    store.apply_triage_verdict(conn, lead["lead_id"], "andrey-s", True,
                               {"role_title": "QA Engineer", "apply_hint": "DM @hr"})
    with conn.cursor() as cur:
        cur.execute(
            "select is_relevant, extracted from telegram_lead_triage "
            "where lead_id = %s and candidate_id = %s", (lead["lead_id"], "andrey-s"))
        is_relevant, extracted = cur.fetchone()
    assert is_relevant is True
    assert extracted["role_title"] == "QA Engineer"

    # Re-triaging the same lead for the same candidate updates the row (upsert),
    # it doesn't raise on the (lead_id, candidate_id) primary key conflict.
    store.apply_triage_verdict(conn, lead["lead_id"], "andrey-s", False,
                               {"note": "actually not a fit"})
    with conn.cursor() as cur:
        cur.execute(
            "select count(*), bool_and(is_relevant = false) from telegram_lead_triage "
            "where lead_id = %s and candidate_id = %s", (lead["lead_id"], "andrey-s"))
        count, all_false = cur.fetchone()
    assert count == 1
    assert all_false is True
