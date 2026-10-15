"""[SAFETY] Регресс C2: заявка, остановленная гардом, должна оставаться

переодобряемой. До фикса fail_claimed_attempt освобождал резервирование
попытки, но approval оставался 'approved' — ux_approval_active (0021) не
пускал новый create_approval, и заявка застревала в submit_blocked навсегда.
"""
import datetime as dt

import pytest

from job_machine.approval import store as approval_store
from job_machine.runtime import control
from job_machine.submit import store
from tests.conftest import apply_migrations


def _approved_application(conn, payload_hash="ph1"):
    with conn.cursor() as cur:
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
    approval_id = approval_store.create_approval(conn, aid, payload_hash, "tok", expires)
    approval_store.approve(conn, aid)
    control.set_submit_enabled(conn, True, actor="test")
    conn.commit()
    return aid, approval_id


def _approval_status(conn, approval_id):
    with conn.cursor() as cur:
        cur.execute("select approval_status from approval where approval_id=%s",
                    (approval_id,))
        return cur.fetchone()[0]


@pytest.mark.db
def test_fail_claimed_attempt_expires_the_approval(db_schema):
    conn, _schema = db_schema
    apply_migrations(conn)
    aid, approval_id = _approved_application(conn)

    claim = store.claim_application(conn, aid, worker_id="w1")
    conn.commit()
    assert claim is not None

    ok = store.fail_claimed_attempt(conn, claim["attempt_id"], "captcha", {})
    conn.commit()
    assert ok is True

    assert _approval_status(conn, approval_id) == "expired"
    with conn.cursor() as cur:
        cur.execute("select reserved_attempt_id from approval where approval_id=%s",
                    (approval_id,))
        assert cur.fetchone()[0] is None
    with conn.cursor() as cur:
        cur.execute("select state from application where application_id=%s", (aid,))
        assert cur.fetchone()[0] == "submit_blocked"


@pytest.mark.db
def test_repackaged_application_can_get_a_new_approval_after_guard_block(db_schema):
    """Тот самый сценарий из отчёта: гард блокирует, владелец переоткрывает и
    переупаковывает (payload_hash меняется), новый approval не должен падать
    с IntegrityError на ux_approval_active."""
    conn, _schema = db_schema
    apply_migrations(conn)
    aid, _approval_id = _approved_application(conn, payload_hash="ph1")

    claim = store.claim_application(conn, aid, worker_id="w1")
    conn.commit()
    store.fail_claimed_attempt(conn, claim["attempt_id"], "captcha", {})
    conn.commit()

    # Владелец переоткрывает и переупаковывает: payload меняется, заявка снова
    # готова к одобрению.
    with conn.cursor() as cur:
        cur.execute(
            "update application set state='pre_submit_ready', payload_hash='ph2', "
            "current_blocker=null, updated_at=now() where application_id=%s",
            (aid,))
    conn.commit()

    expires = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=2)
    new_approval_id = approval_store.create_approval(conn, aid, "ph2", "tok2", expires)
    conn.commit()

    assert new_approval_id
    rec = approval_store.load_by_application(conn, aid)
    assert rec["approval_status"] == "pending"
    assert rec["payload_hash"] == "ph2"


@pytest.mark.db
def test_create_approval_does_not_fail_on_expired_pending_row(db_schema):
    """Протухший (TTL истёк) pending не блокирует создание нового одобрения —
    ни один код-путь в проекте не пишет approval_status='expired' по TTL, но
    create_approval должен уметь ленивую очистку сам."""
    conn, _schema = db_schema
    apply_migrations(conn)
    with conn.cursor() as cur:
        cur.execute("insert into candidate (candidate_id, name) "
                    "values ('andrey-s','Andrey') on conflict do nothing")
        cur.execute("insert into vacancy (canonical_url) values "
                    "('https://boards.example/jobs/2') returning vacancy_id")
        vacancy_id = cur.fetchone()[0]
        cur.execute(
            "insert into application (vacancy_id, candidate_id, state, payload_hash) "
            "values (%s,'andrey-s','pre_submit_ready','ph1') returning application_id",
            (vacancy_id,))
        aid = str(cur.fetchone()[0])
    conn.commit()

    stale_expiry = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1)
    stale_id = approval_store.create_approval(conn, aid, "ph1", "stale-tok", stale_expiry)
    conn.commit()
    assert _approval_status(conn, stale_id) == "pending"  # протух по TTL, но не помечен

    expires = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=2)
    new_id = approval_store.create_approval(conn, aid, "ph1", "fresh-tok", expires)
    conn.commit()

    assert new_id != stale_id
    assert _approval_status(conn, stale_id) == "expired"
    assert _approval_status(conn, new_id) == "pending"


@pytest.mark.db
def test_consumed_approval_is_never_touched_by_create_approval(db_schema):
    conn, _schema = db_schema
    apply_migrations(conn)
    aid, approval_id = _approved_application(conn, payload_hash="ph1")

    claim = store.claim_application(conn, aid, worker_id="w1")
    conn.commit()
    assert store.mark_clicking(conn, claim["attempt_id"]) is True
    conn.commit()
    assert _approval_status(conn, approval_id) == "consumed"

    # Заявка каким-то образом снова просит нового одобрения (например,
    # submit_unknown -> ручной refile) — исторический consumed не должен
    # ни блокировать вставку, ни менять статус.
    with conn.cursor() as cur:
        cur.execute(
            "update application set state='pre_submit_ready', updated_at=now() "
            "where application_id=%s", (aid,))
    conn.commit()

    expires = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=2)
    new_id = approval_store.create_approval(conn, aid, "ph1", "tok-new", expires)
    conn.commit()

    assert new_id != str(approval_id)
    assert _approval_status(conn, approval_id) == "consumed"


@pytest.mark.db
def test_happy_path_approval_still_works(db_schema):
    """Regression guard: обычный путь одобрения без предшествующих строк не
    должен ломаться новой очисткой в create_approval."""
    conn, _schema = db_schema
    apply_migrations(conn)
    with conn.cursor() as cur:
        cur.execute("insert into candidate (candidate_id, name) "
                    "values ('andrey-s','Andrey') on conflict do nothing")
        cur.execute("insert into vacancy (canonical_url) values "
                    "('https://boards.example/jobs/3') returning vacancy_id")
        vacancy_id = cur.fetchone()[0]
        cur.execute(
            "insert into application (vacancy_id, candidate_id, state, payload_hash) "
            "values (%s,'andrey-s','pre_submit_ready','ph1') returning application_id",
            (vacancy_id,))
        aid = str(cur.fetchone()[0])
    conn.commit()

    expires = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=2)
    approval_id = approval_store.create_approval(conn, aid, "ph1", "tok", expires)
    conn.commit()
    assert approval_store.approve(conn, aid) is True
    conn.commit()
    assert _approval_status(conn, approval_id) == "approved"
