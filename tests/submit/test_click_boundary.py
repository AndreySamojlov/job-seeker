import pytest

from job_machine.submit import store
from tests.conftest import apply_migrations
from tests.submit.test_claim import _approved_application


@pytest.mark.db
def test_mark_clicking_consumes_approval(db_schema):
    conn, _schema = db_schema
    apply_migrations(conn)
    aid = _approved_application(conn)
    claim = store.claim_application(conn, aid, worker_id="w1")
    conn.commit()

    assert store.mark_clicking(conn, claim["attempt_id"]) is True
    conn.commit()

    with conn.cursor() as cur:
        cur.execute("select status, click_started_at from submission_attempt "
                    "where attempt_id=%s", (claim["attempt_id"],))
        status, click_started_at = cur.fetchone()
        assert status == "clicking"
        assert click_started_at is not None
        cur.execute("select approval_status, consumed_at from approval "
                    "where approval_id=%s", (claim["approval_id"],))
        approval_status, consumed_at = cur.fetchone()
        assert approval_status == "consumed"
        assert consumed_at is not None


@pytest.mark.db
def test_mark_clicking_twice_is_refused(db_schema):
    conn, _schema = db_schema
    apply_migrations(conn)
    aid = _approved_application(conn)
    claim = store.claim_application(conn, aid, worker_id="w1")
    conn.commit()
    store.mark_clicking(conn, claim["attempt_id"])
    conn.commit()

    assert store.mark_clicking(conn, claim["attempt_id"]) is False


@pytest.mark.db
def test_verification_fenced_to_live_clicking_attempt(db_schema):
    conn, _schema = db_schema
    apply_migrations(conn)
    aid = _approved_application(conn)
    claim = store.claim_application(conn, aid, worker_id="w1")
    conn.commit()

    assert store.can_continue_verification(conn, claim["attempt_id"]) is False
    store.mark_clicking(conn, claim["attempt_id"])
    conn.commit()
    assert store.can_continue_verification(conn, claim["attempt_id"]) is True
