import pytest

from job_machine.submit import store
from tests.conftest import apply_migrations
from tests.submit.test_claim import _approved_application


def _expire_lease(conn, attempt_id):
    with conn.cursor() as cur:
        cur.execute("update submission_attempt set lease_until=now() - interval '1 hour' "
                    "where attempt_id=%s", (attempt_id,))
    conn.commit()


@pytest.mark.db
def test_stale_claimed_attempt_returns_to_approved(db_schema):
    conn, _schema = db_schema
    apply_migrations(conn)
    aid = _approved_application(conn)
    claim = store.claim_application(conn, aid, worker_id="w1")
    conn.commit()
    _expire_lease(conn, claim["attempt_id"])

    summary = store.recover_stale_attempts(conn)
    conn.commit()

    assert summary["released"] == 1
    with conn.cursor() as cur:
        cur.execute("select state from application where application_id=%s", (aid,))
        assert cur.fetchone()[0] == "approved"
        cur.execute("select status from submission_attempt where attempt_id=%s",
                    (claim["attempt_id"],))
        assert cur.fetchone()[0] == "failed"
        cur.execute("select reserved_attempt_id from approval where application_id=%s",
                    (aid,))
        assert cur.fetchone()[0] is None


@pytest.mark.db
def test_stale_clicking_attempt_becomes_unknown_not_released(db_schema):
    conn, _schema = db_schema
    apply_migrations(conn)
    aid = _approved_application(conn)
    claim = store.claim_application(conn, aid, worker_id="w1")
    conn.commit()
    store.mark_clicking(conn, claim["attempt_id"])
    conn.commit()
    _expire_lease(conn, claim["attempt_id"])

    summary = store.recover_stale_attempts(conn)
    conn.commit()

    assert summary["quarantined"] == 1
    assert summary["released"] == 0
    with conn.cursor() as cur:
        cur.execute("select state from application where application_id=%s", (aid,))
        assert cur.fetchone()[0] == "submit_unknown"


@pytest.mark.db
def test_live_lease_is_untouched(db_schema):
    conn, _schema = db_schema
    apply_migrations(conn)
    aid = _approved_application(conn)
    store.claim_application(conn, aid, worker_id="w1")
    conn.commit()

    summary = store.recover_stale_attempts(conn)
    conn.commit()

    assert summary == {"released": 0, "quarantined": 0}
