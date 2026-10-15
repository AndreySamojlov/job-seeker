import uuid
from datetime import datetime, timedelta, timezone

import pytest

from job_machine.approval import service, store
from job_machine.db import migrate


def _apply(conn):
    for m in migrate.pending(migrate.discover_migrations("db/migrations"),
                             migrate.applied_migrations(conn)):
        migrate.apply_migration(conn, m)


def _seed_app(conn, state="pre_submit_ready", payload_hash="ph1"):
    with conn.cursor() as cur:
        cur.execute(
            "insert into vacancy (company, title, canonical_url, vacancy_status, state) "
            "values ('Acme','QA Lead','https://acme/b','triaged','triaged') "
            "returning vacancy_id")
        vid = cur.fetchone()[0]
        cur.execute(
            "insert into application (vacancy_id, candidate_id, verdict, package_status, state, "
            "payload_hash) "
            "values (%s,'andrey-s','apply','none',%s,%s) returning application_id",
            (vid, state, payload_hash))
        return str(cur.fetchone()[0])


@pytest.mark.db
def test_request_approval_creates_pending_with_token(db_schema):
    conn, _ = db_schema
    _apply(conn)
    aid = _seed_app(conn)
    conn.commit()
    approval_id = service.request_approval(conn, aid, "ph1")
    conn.commit()
    rec = store.load_by_application(conn, aid)
    assert rec["approval_status"] == "pending"
    assert len(rec["approval_token"]) == 64   # secrets.token_hex(32)
    assert rec["expires_at"] > datetime.now(tz=timezone.utc)
    assert approval_id


@pytest.mark.db
def test_process_approval_request_creates_one_per_app(db_schema):
    conn, _ = db_schema
    _apply(conn)
    aid = _seed_app(conn)
    conn.commit()
    result = service.process_approval_request(conn, limit=10)
    conn.commit()
    assert result["count"] == 1
    assert result["items"][0]["application_id"] == aid
    # Second call: application already has pending → no new record
    result2 = service.process_approval_request(conn, limit=10)
    conn.commit()
    assert result2["count"] == 0
