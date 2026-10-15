import datetime as dt

import pytest

from job_machine.approval import store as approval_store
from job_machine.runtime import control
from job_machine.submit import store
from tests.conftest import apply_migrations


def _approved_application(conn, payload_hash="ph1"):
    with conn.cursor() as cur:
        # candidate.name — NOT NULL (обнаружено при исполнении Task 5).
        cur.execute("insert into candidate (candidate_id, name) "
                    "values ('andrey-s','Andrey') on conflict do nothing")
        cur.execute("insert into vacancy (canonical_url, ats_family) values "
                    "('https://boards.example/jobs/1','greenhouse') returning vacancy_id")
        vacancy_id = cur.fetchone()[0]
        cur.execute(
            "insert into application (vacancy_id, candidate_id, state, payload_hash) "
            "values (%s,'andrey-s','pre_submit_ready',%s) returning application_id",
            (vacancy_id, payload_hash))
        aid = str(cur.fetchone()[0])
    expires = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=2)
    approval_store.create_approval(conn, aid, payload_hash, "tok", expires)
    approval_store.approve(conn, aid)
    control.set_submit_enabled(conn, True, actor="test")
    conn.commit()
    return aid


@pytest.mark.db
def test_claim_reserves_approval_and_moves_to_submitting(db_schema):
    conn, _schema = db_schema
    apply_migrations(conn)
    aid = _approved_application(conn)

    claim = store.claim_application(conn, aid, worker_id="w1")
    conn.commit()

    assert claim is not None
    assert claim["application_id"] == aid
    with conn.cursor() as cur:
        cur.execute("select state from application where application_id=%s", (aid,))
        assert cur.fetchone()[0] == "submitting"
        cur.execute("select status from submission_attempt where application_id=%s", (aid,))
        assert cur.fetchone()[0] == "claimed"
        cur.execute("select reserved_attempt_id from approval where application_id=%s", (aid,))
        assert str(cur.fetchone()[0]) == claim["attempt_id"]


@pytest.mark.db
def test_second_claim_of_same_application_returns_none(db_schema):
    conn, _schema = db_schema
    apply_migrations(conn)
    aid = _approved_application(conn)

    first = store.claim_application(conn, aid, worker_id="w1")
    conn.commit()
    second = store.claim_application(conn, aid, worker_id="w2")
    conn.commit()

    assert first is not None
    assert second is None


@pytest.mark.db
def test_claim_refused_while_switch_disabled(db_schema):
    conn, _schema = db_schema
    apply_migrations(conn)
    aid = _approved_application(conn)
    control.set_submit_enabled(conn, False, actor="test")
    conn.commit()

    assert store.claim_application(conn, aid, worker_id="w1") is None
    conn.commit()
    with conn.cursor() as cur:
        cur.execute("select state from application where application_id=%s", (aid,))
        assert cur.fetchone()[0] == "approved"
