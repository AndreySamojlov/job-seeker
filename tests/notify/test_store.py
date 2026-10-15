import uuid

import pytest
from psycopg.types.json import Jsonb

from job_machine.db import migrate
from job_machine.notify import store


def _apply(conn):
    for m in migrate.pending(migrate.discover_migrations("db/migrations"),
                             migrate.applied_migrations(conn)):
        migrate.apply_migration(conn, m)


def _seed_app_event(conn, event_type, payload, candidate_id="andrey-s",
                    company="Acme", role="QA Engineer"):
    """Вставить vacancy+application+event; вернуть (application_id, event_id)."""
    uniq = uuid.uuid4().hex[:8]
    with conn.cursor() as cur:
        cur.execute(
            "insert into vacancy (source, source_url, canonical_url, title, company, "
            "vacancy_status, state) values ('greenhouse', %s, %s, %s, %s, "
            "'triaged', 'triaged') returning vacancy_id",
            (f"https://api/{event_type}/{uniq}", f"https://acme/{event_type}/{uniq}",
             role, company))
        vid = cur.fetchone()[0]
        cur.execute(
            "insert into application (vacancy_id, candidate_id, state, payload_hash) "
            "values (%s, %s, 'pre_submit_ready', 'h') returning application_id",
            (vid, candidate_id))
        aid = cur.fetchone()[0]
        cur.execute(
            "insert into event (entity_type, entity_id, event_type, payload_json) "
            "values ('application', %s, %s, %s) returning event_id",
            (aid, event_type, Jsonb(payload)))
        eid = cur.fetchone()[0]
    return aid, eid


@pytest.mark.db
def test_select_pending_returns_curated_with_route(db_schema):
    conn, _ = db_schema
    _apply(conn)
    _, eid = _seed_app_event(conn, "application.submitted",
                             {"confirmation_url": "https://acme/thanks"})
    conn.commit()
    rows = store.select_pending(conn)
    assert len(rows) == 1
    r = rows[0]
    assert r["event_id"] == eid
    assert r["event_type"] == "application.submitted"
    assert r["name"] == "Andrey Samoylov"   # из candidate 'andrey-s'
    assert r["company"] == "Acme" and r["title"] == "QA Engineer"
    assert r["payload_json"]["confirmation_url"] == "https://acme/thanks"


@pytest.mark.db
def test_select_pending_ignores_non_curated(db_schema):
    conn, _ = db_schema
    _apply(conn)
    _seed_app_event(conn, "application.approval_payload_drift", {})
    _seed_app_event(conn, "application.triaged", {})
    conn.commit()
    assert store.select_pending(conn) == []


@pytest.mark.db
def test_fill_blocked_only_mandatory_unknown(db_schema):
    conn, _ = db_schema
    _apply(conn)
    _seed_app_event(conn, "application.fill_blocked", {"blocker": "broken_flow"})
    _, eid = _seed_app_event(conn, "application.fill_blocked",
                             {"blocker": "mandatory_unknown", "unmatched": ["salary"]})
    conn.commit()
    rows = store.select_pending(conn)
    assert [r["event_id"] for r in rows] == [eid]


@pytest.mark.db
def test_claim_then_mark_sent_removes_from_pending(db_schema):
    conn, _ = db_schema
    _apply(conn)
    _, eid = _seed_app_event(conn, "application.submitted", {})
    conn.commit()
    store.claim(conn, eid, "submitted", "272425172")
    conn.commit()
    # claim оставляет status='pending' → всё ещё в выборке (ретрай)
    assert [r["event_id"] for r in store.select_pending(conn)] == [eid]
    store.mark_sent(conn, eid, 99)
    conn.commit()
    # sent → выпадает из выборки
    assert store.select_pending(conn) == []
    with conn.cursor() as cur:
        cur.execute("select status, tg_message_id from notification_dispatch "
                    "where event_id=%s", (eid,))
        assert cur.fetchone() == ("sent", 99)


@pytest.mark.db
def test_daily_exists_and_record(db_schema):
    conn, _ = db_schema
    _apply(conn)
    import datetime
    d = datetime.date(2026, 7, 2)
    assert store.daily_exists(conn, d) is False
    store.record_daily(conn, d, "272425172", 7)
    conn.commit()
    assert store.daily_exists(conn, d) is True


@pytest.mark.db
def test_select_pending_includes_fit_score_when_scored(db_schema):
    conn, _ = db_schema
    _apply(conn)
    aid, _ = _seed_app_event(conn, "application.submitted", {})
    with conn.cursor() as cur:
        cur.execute("select candidate_id, vacancy_id from application "
                    "where application_id=%s", (aid,))
        cand_id, vac_id = cur.fetchone()
        cur.execute(
            "insert into triage_result (candidate_id, vacancy_id, verdict, "
            "fit_score, fit_band) values (%s, %s, 'apply', 72, 'strong')",
            (cand_id, vac_id))
    conn.commit()
    rows = store.select_pending(conn)
    assert rows[0]["fit_score"] == 72
    assert rows[0]["fit_band"] == "strong"


@pytest.mark.db
def test_select_pending_fit_score_null_when_not_scored(db_schema):
    conn, _ = db_schema
    _apply(conn)
    _seed_app_event(conn, "application.submitted", {})
    conn.commit()
    rows = store.select_pending(conn)
    assert rows[0]["fit_score"] is None
    assert rows[0]["fit_band"] is None


@pytest.mark.db
def test_daily_stats_counts_per_candidate(db_schema):
    conn, _ = db_schema
    _apply(conn)
    # одна submitted-заявка Андрея за последние сутки
    _seed_app_event(conn, "application.submitted", {})
    conn.commit()
    stats = {s["candidate_id"]: s for s in store.daily_stats(conn)}
    assert stats["andrey-s"]["submitted"] == 1
    assert stats["andrey-s"]["awaiting"] == 0


@pytest.mark.db
def test_daily_stats_counts_live_handoff_blockers(db_schema):
    """captcha/mfa/anti_bot — заявка с живой handoff-сессией, ждущей владельца —
    должна попадать в дневную сводку "заблокировано" наравне с handoff_manual/
    mandatory_unknown (иначе выпадает из видимости, хотя требует действия)."""
    conn, _ = db_schema
    _apply(conn)
    aid, _ = _seed_app_event(conn, "application.fill_blocked", {"blocker": "captcha"})
    with conn.cursor() as cur:
        cur.execute("update application set current_blocker='captcha' "
                    "where application_id=%s", (aid,))
    conn.commit()
    stats = {s["candidate_id"]: s for s in store.daily_stats(conn)}
    assert stats["andrey-s"]["blocked"] == 1


@pytest.mark.db
def test_daily_stats_excludes_failed_refiled_applications(db_schema):
    """regen.refile_application leaves the old (now state='failed') row's
    current_blocker intact for diagnostic history — it must not inflate the daily
    Telegram 'blocked' count forever, even for handoff_manual (in the allowlist)."""
    conn, _ = db_schema
    _apply(conn)
    aid, _ = _seed_app_event(conn, "application.fill_blocked", {"blocker": "handoff_manual"})
    with conn.cursor() as cur:
        cur.execute("update application set state='failed', current_blocker='handoff_manual' "
                    "where application_id=%s", (aid,))
    conn.commit()
    stats = {s["candidate_id"]: s for s in store.daily_stats(conn)}
    assert stats["andrey-s"]["blocked"] == 0
