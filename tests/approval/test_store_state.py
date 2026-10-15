import datetime as dt

import pytest

from job_machine.approval import store
from tests.conftest import apply_migrations


def _seed(conn, payload_hash="ph1"):
    with conn.cursor() as cur:
        cur.execute("insert into candidate (candidate_id, name) values ('andrey-s','Andrey') "
                    "on conflict do nothing")
        cur.execute("insert into vacancy (canonical_url) values "
                    "('https://boards.example/jobs/1') returning vacancy_id")
        vacancy_id = cur.fetchone()[0]
        cur.execute(
            "insert into application (vacancy_id, candidate_id, state, payload_hash) "
            "values (%s,'andrey-s','pre_submit_ready',%s) returning application_id",
            (vacancy_id, payload_hash))
        return str(cur.fetchone()[0])


def _state(conn, application_id):
    with conn.cursor() as cur:
        cur.execute("select state from application where application_id=%s",
                    (application_id,))
        return cur.fetchone()[0]


@pytest.mark.db
def test_approve_moves_application_to_approved(db_schema):
    conn, _schema = db_schema
    apply_migrations(conn)
    aid = _seed(conn)
    expires = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=2)
    store.create_approval(conn, aid, "ph1", "tok", expires)
    conn.commit()

    assert store.approve(conn, aid) is True
    conn.commit()
    assert _state(conn, aid) == "approved"


@pytest.mark.db
def test_payload_drift_leaves_state_untouched(db_schema):
    conn, _schema = db_schema
    apply_migrations(conn)
    aid = _seed(conn)
    expires = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=2)
    store.create_approval(conn, aid, "ph1", "tok", expires)
    with conn.cursor() as cur:
        cur.execute("update application set payload_hash='ph2' where application_id=%s",
                    (aid,))
    conn.commit()

    assert store.approve(conn, aid) is False
    conn.commit()
    assert _state(conn, aid) == "pre_submit_ready"
