import datetime
import uuid

import pytest
from psycopg.types.json import Jsonb

from job_machine.db import migrate
from job_machine.notify import service


def _apply(conn):
    for m in migrate.pending(migrate.discover_migrations("db/migrations"),
                             migrate.applied_migrations(conn)):
        migrate.apply_migration(conn, m)


def _seed_app_event(conn, event_type, payload, candidate_id="andrey-s",
                    company="Acme", role="QA Engineer"):
    suffix = uuid.uuid4().hex[:8]
    with conn.cursor() as cur:
        cur.execute(
            "insert into vacancy (source, source_url, canonical_url, title, company, "
            "vacancy_status, state) values ('greenhouse', %s, %s, %s, %s, "
            "'triaged', 'triaged') returning vacancy_id",
            (f"https://api/{event_type}/{suffix}",
             f"https://acme/{event_type}/{suffix}", role, company))
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


class FakeSender:
    def __init__(self, fail_times=0):
        self.sent = []
        self._fail_times = fail_times

    def send_message(self, chat_id, text, parse_mode="HTML"):
        if self._fail_times > 0:
            self._fail_times -= 1
            raise RuntimeError("smoke: send failed")
        self.sent.append((chat_id, text))
        return 100 + len(self.sent)


@pytest.mark.db
def test_dispatch_sends_and_marks(db_schema):
    conn, _ = db_schema
    _apply(conn)
    _seed_app_event(conn, "application.submitted", {"confirmation_url": "https://x"})
    conn.commit()
    sender = FakeSender()
    result = service.dispatch(conn, sender, "272425172")
    assert result["sent"] == 1
    assert sender.sent[0][0] == "272425172"
    assert "Andrey Samoylov" in sender.sent[0][1]


@pytest.mark.db
def test_dispatch_is_idempotent_on_rerun(db_schema):
    conn, _ = db_schema
    _apply(conn)
    _seed_app_event(conn, "application.submitted", {})
    conn.commit()
    sender = FakeSender()
    service.dispatch(conn, sender, "272425172")
    second = service.dispatch(conn, sender, "272425172")   # уже sent
    assert second["sent"] == 0
    assert len(sender.sent) == 1   # без дубля


@pytest.mark.db
def test_dispatch_retries_pending_after_failure(db_schema):
    conn, _ = db_schema
    _apply(conn)
    _seed_app_event(conn, "application.submitted", {})
    conn.commit()
    failing = FakeSender(fail_times=1)
    r1 = service.dispatch(conn, failing, "272425172")
    assert r1["failed"] == 1 and r1["sent"] == 0
    # строка осталась pending → следующий тик доставляет
    ok = FakeSender()
    r2 = service.dispatch(conn, ok, "272425172")
    assert r2["sent"] == 1
    assert len(ok.sent) == 1


@pytest.mark.db
def test_daily_summary_sends_once_per_day(db_schema):
    conn, _ = db_schema
    _apply(conn)
    _seed_app_event(conn, "application.submitted", {})
    conn.commit()
    sender = FakeSender()
    now = datetime.datetime(2026, 7, 2, 9, 0, tzinfo=datetime.timezone.utc)
    r1 = service.daily_summary(conn, sender, "272425172", now=now)
    assert r1["status"] == "sent"
    assert len(sender.sent) == 1
    r2 = service.daily_summary(conn, sender, "272425172", now=now)   # тот же день
    assert r2["status"] == "already_sent"
    assert len(sender.sent) == 1


# ─── n8n-send путь ───

@pytest.mark.db
def test_pending_messages_returns_and_marks_delivered(db_schema):
    conn, _ = db_schema
    _apply(conn)
    _seed_app_event(conn, "application.submitted", {"confirmation_url": "https://x"})
    conn.commit()
    msgs = service.pending_messages(conn, "272425172")
    assert len(msgs) == 1
    assert msgs[0]["chat_id"] == "272425172"
    assert "Andrey Samoylov" in msgs[0]["text"]
    # помечено доставленным → повторный вызов пуст (ledger-дедуп, без дублей меж тиками)
    assert service.pending_messages(conn, "272425172") == []


@pytest.mark.db
def test_summary_now_ignores_daily_dedup(db_schema):
    conn, _ = db_schema
    _apply(conn)
    _seed_app_event(conn, "application.submitted", {})
    conn.commit()
    now = datetime.datetime(2026, 7, 2, 9, 0, tzinfo=datetime.timezone.utc)
    store_result = service.daily_pending(conn, "272425172", now=now)
    assert len(store_result) == 1   # дневная сводка уже "отправлена" на сегодня
    # запрос владельца по требованию — не гейтится дневным дедупом
    on_demand = service.summary_now(conn, "272425172", now=now)
    assert len(on_demand) == 1
    assert on_demand[0]["chat_id"] == "272425172"
    assert "Andrey Samoylov" in on_demand[0]["text"]


@pytest.mark.db
def test_daily_pending_once_per_day(db_schema):
    conn, _ = db_schema
    _apply(conn)
    _seed_app_event(conn, "application.submitted", {})
    conn.commit()
    now = datetime.datetime(2026, 7, 2, 9, 0, tzinfo=datetime.timezone.utc)
    first = service.daily_pending(conn, "272425172", now=now)
    assert len(first) == 1 and first[0]["chat_id"] == "272425172"
    second = service.daily_pending(conn, "272425172", now=now)   # тот же день
    assert second == []
