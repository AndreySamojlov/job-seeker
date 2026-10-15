import pytest

from job_machine.db import migrate
from job_machine.mcp import store, tools


def _apply(conn):
    for m in migrate.pending(migrate.discover_migrations("db/migrations"),
                             migrate.applied_migrations(conn)):
        migrate.apply_migration(conn, m)


def _seed(conn):
    with conn.cursor() as cur:
        cur.execute("insert into vacancy (company, title, canonical_url, ats_family, "
                    "vacancy_status, state) values ('Acme','QA Lead',"
                    "'https://acme/apply','greenhouse','triaged','triaged') "
                    "returning vacancy_id")
        vid = cur.fetchone()[0]
        cur.execute("insert into application (vacancy_id, candidate_id, state, payload_hash) "
                    "values (%s,'andrey-s','pre_submit_ready','ph1') returning application_id",
                    (vid,))
        aid = cur.fetchone()[0]
        cur.execute("insert into event (entity_type, entity_id, event_type, payload_json) "
                    "values ('application', %s, 'application.pre_submit_ready', "
                    "'{\"screenshot_path\": \"/art/shot.png\"}'::jsonb)", (aid,))
    return str(aid)


@pytest.mark.db
def test_query_ready_queue_returns_rows(db_schema):
    conn, _ = db_schema
    _apply(conn)
    aid = _seed(conn)
    conn.commit()
    rows = store.query_ready_queue(conn, candidate_id="andrey-s", limit=10)
    assert len(rows) == 1
    assert rows[0]["application_id"] == aid
    assert rows[0]["company"] == "Acme"
    assert rows[0]["screenshot_path"] == "/art/shot.png"


@pytest.mark.db
def test_query_ready_queue_all_spans_candidates(db_schema):
    """Дашборд — глобальный read-only обзор: очередь по ВСЕМ кандидатам, не одному."""
    conn, _ = db_schema
    _apply(conn)
    with conn.cursor() as cur:
        cur.execute("insert into candidate (candidate_id, name) values ('tester-b','B')")
        cur.execute("insert into vacancy (company, title, canonical_url, ats_family, "
                    "vacancy_status, state) values ('Globex','PM',"
                    "'https://globex/apply','lever','triaged','triaged') "
                    "returning vacancy_id")
        vid = cur.fetchone()[0]
        cur.execute("insert into application (vacancy_id, candidate_id, state, payload_hash) "
                    "values (%s,'tester-b','pre_submit_ready','ph2') returning application_id",
                    (vid,))
    aid_a = _seed(conn)
    conn.commit()
    rows = store.query_ready_queue_all(conn, limit=10)
    assert len(rows) == 2
    by_company = {r["company"]: r for r in rows}
    assert by_company["Acme"]["candidate_id"] == "andrey-s"
    assert by_company["Acme"]["application_id"] == aid_a
    assert by_company["Globex"]["candidate_id"] == "tester-b"


class FakeConn:
    def close(self): pass


def test_list_ready_tool_delegates(monkeypatch):
    monkeypatch.setattr(tools.store, "query_ready_queue",
                        lambda conn, candidate_id, limit: [{"application_id": "a1", "company": "Acme"}])
    out = tools.list_ready(FakeConn(), "andrey-s", limit=5)
    assert out[0]["application_id"] == "a1"
