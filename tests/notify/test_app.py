import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from job_machine.db import migrate
from job_machine.db.connection import connect
from job_machine.notify.app import create_app


def _apply(conn):
    for m in migrate.pending(migrate.discover_migrations("db/migrations"),
                             migrate.applied_migrations(conn)):
        migrate.apply_migration(conn, m)


class FakeSender:
    def __init__(self):
        self.sent = []

    def send_message(self, chat_id, text, parse_mode="HTML"):
        self.sent.append((chat_id, text))
        return 1

    def close(self):
        pass


def test_healthz():
    app = create_app(conn_factory=lambda: None,
                     sender_factory=lambda: FakeSender(), owner_chat_id="1")
    client = TestClient(app)
    assert client.get("/healthz").json() == {"status": "ok"}


def test_dispatch_closes_conn_when_sender_factory_raises():
    closed = {"n": 0}

    class FakeConn:
        def close(self):
            closed["n"] += 1

    def boom_sender():
        raise RuntimeError("no token")

    app = create_app(conn_factory=lambda: FakeConn(),
                     sender_factory=boom_sender, owner_chat_id="1")
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post("/notify/dispatch")
    assert resp.status_code == 500
    assert closed["n"] == 1   # conn закрыт несмотря на сбой sender_factory


@pytest.mark.db
def test_dispatch_endpoint(db_schema):
    conn, schema = db_schema
    _apply(conn)
    with conn.cursor() as cur:
        cur.execute(
            "insert into vacancy (source, source_url, canonical_url, title, company, "
            "vacancy_status, state) values ('greenhouse','u','https://acme/j','QA',"
            "'Acme','triaged','triaged') returning vacancy_id")
        vid = cur.fetchone()[0]
        cur.execute("insert into application (vacancy_id, candidate_id, state, "
                    "payload_hash) values (%s,'andrey-s','pre_submit_ready','h') "
                    "returning application_id", (vid,))
        aid = cur.fetchone()[0]
        cur.execute("insert into event (entity_type, entity_id, event_type, "
                    "payload_json) values ('application', %s, 'application.submitted', %s)",
                    (aid, Jsonb({})))
    conn.commit()

    sender = FakeSender()

    def conn_factory():
        # свежее соединение к тому же temp-схеме; эндпоинт его закрывает
        c = connect()
        with c.cursor() as cur:
            cur.execute(f'set search_path to "{schema}"')
        return c

    app = create_app(conn_factory=conn_factory,
                     sender_factory=lambda: sender, owner_chat_id="272425172")
    client = TestClient(app)
    resp = client.post("/notify/dispatch")
    assert resp.status_code == 200
    assert resp.json()["sent"] == 1
    assert sender.sent and sender.sent[0][0] == "272425172"


@pytest.mark.db
def test_pending_endpoint_returns_messages(db_schema):
    conn, schema = db_schema
    _apply(conn)
    with conn.cursor() as cur:
        cur.execute(
            "insert into vacancy (source, source_url, canonical_url, title, company, "
            "vacancy_status, state) values ('greenhouse','u2','https://acme/j2','QA',"
            "'Acme','triaged','triaged') returning vacancy_id")
        vid = cur.fetchone()[0]
        cur.execute("insert into application (vacancy_id, candidate_id, state, "
                    "payload_hash) values (%s,'andrey-s','pre_submit_ready','h') "
                    "returning application_id", (vid,))
        aid = cur.fetchone()[0]
        cur.execute("insert into event (entity_type, entity_id, event_type, "
                    "payload_json) values ('application', %s, 'application.submitted', %s)",
                    (aid, Jsonb({})))
    conn.commit()

    def conn_factory():
        c = connect()
        with c.cursor() as cur:
            cur.execute(f'set search_path to "{schema}"')
        return c

    app = create_app(conn_factory=conn_factory,
                     sender_factory=lambda: FakeSender(), owner_chat_id="272425172")
    client = TestClient(app)
    resp = client.post("/notify/pending")
    assert resp.status_code == 200
    msgs = resp.json()["messages"]
    assert len(msgs) == 1
    assert msgs[0]["chat_id"] == "272425172"
    assert "Andrey Samoylov" in msgs[0]["text"]
    # повторный вызов пуст — событие помечено доставленным (ledger-дедуп)
    assert client.post("/notify/pending").json()["messages"] == []


@pytest.mark.db
def test_summary_endpoint_returns_messages(db_schema):
    conn, schema = db_schema
    _apply(conn)
    with conn.cursor() as cur:
        cur.execute(
            "insert into vacancy (source, source_url, canonical_url, title, company, "
            "vacancy_status, state) values ('greenhouse','u3','https://acme/j3','QA',"
            "'Acme','triaged','triaged') returning vacancy_id")
        vid = cur.fetchone()[0]
        cur.execute("insert into application (vacancy_id, candidate_id, state, "
                    "payload_hash) values (%s,'andrey-s','pre_submit_ready','h') "
                    "returning application_id", (vid,))
        aid = cur.fetchone()[0]
        cur.execute("insert into event (entity_type, entity_id, event_type, "
                    "payload_json) values ('application', %s, 'application.submitted', %s)",
                    (aid, Jsonb({})))
    conn.commit()

    def conn_factory():
        c = connect()
        with c.cursor() as cur:
            cur.execute(f'set search_path to "{schema}"')
        return c

    app = create_app(conn_factory=conn_factory,
                     sender_factory=lambda: FakeSender(), owner_chat_id="272425172")
    client = TestClient(app)
    resp = client.post("/notify/summary")
    assert resp.status_code == 200
    msgs = resp.json()["messages"]
    assert len(msgs) == 1
    assert msgs[0]["chat_id"] == "272425172"
    assert "Andrey Samoylov" in msgs[0]["text"]
    # запрос по требованию не дедупится и не блокирует плановую дневную сводку
    resp2 = client.post("/notify/summary")
    assert len(resp2.json()["messages"]) == 1
