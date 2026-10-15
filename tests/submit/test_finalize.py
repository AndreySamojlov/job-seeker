import pytest

from job_machine.browser.schema import SubmitResult
from job_machine.submit import store
from tests.conftest import apply_migrations
from tests.submit.test_claim import _approved_application


def _clicking_attempt(conn):
    aid = _approved_application(conn)
    claim = store.claim_application(conn, aid, worker_id="w1")
    conn.commit()
    store.mark_clicking(conn, claim["attempt_id"])
    conn.commit()
    return aid, claim["attempt_id"]


def _full_proof():
    return SubmitResult(
        submitted=True,
        click_performed=True,
        confirmation_url="https://boards.example/jobs/1/confirmation",
        confirmation_signal="confirmation_url",
        form_absent=True,
        errors_absent=True,
        screenshot_path="/data/artifacts/browser/x_confirm.png",
    )


def _states(conn, application_id, attempt_id):
    with conn.cursor() as cur:
        cur.execute("select state from application where application_id=%s",
                    (application_id,))
        app_state = cur.fetchone()[0]
        cur.execute("select status from submission_attempt where attempt_id=%s",
                    (attempt_id,))
        return app_state, cur.fetchone()[0]


@pytest.mark.db
def test_full_proof_confirms(db_schema, tmp_path):
    conn, _schema = db_schema
    apply_migrations(conn)
    aid, attempt_id = _clicking_attempt(conn)
    shot = tmp_path / "confirm.png"
    shot.write_bytes(b"png-bytes")
    result = _full_proof()
    result.screenshot_path = str(shot)

    assert store.finalize_confirmed(conn, attempt_id, result) is True
    conn.commit()
    assert _states(conn, aid, attempt_id) == ("submitted", "confirmed")
    with conn.cursor() as cur:
        cur.execute(
            "select payload_json from event where event_type='application.submitted' "
            "and entity_id=%s", (aid,))
        payload = cur.fetchone()[0]
    # Регресс: confirmation_url пропал из payload события application.submitted
    # (только путь к скриншоту в артефакте) — потребители (funnel.py CSV,
    # load_submit_confirmation, notify/render.py) читают именно payload события.
    assert payload["confirmation_url"] == "https://boards.example/jobs/1/confirmation"
    # Новые поля доказательства (T8) не должны пропасть при возврате confirmation_url.
    assert payload["attempt_id"] == attempt_id
    assert payload["confirmation_signal"] == "confirmation_url"
    assert payload["resolution_source"] == "browser"
    assert payload["screenshot_sha256"]


@pytest.mark.db
def test_incomplete_proof_refuses_to_confirm(db_schema):
    conn, _schema = db_schema
    apply_migrations(conn)
    aid, attempt_id = _clicking_attempt(conn)
    result = _full_proof()
    result.form_absent = False

    assert store.finalize_confirmed(conn, attempt_id, result) is False
    conn.commit()
    assert _states(conn, aid, attempt_id) == ("submitting", "clicking")


@pytest.mark.db
def test_recovered_unknown_attempt_still_accepts_full_proof(db_schema, tmp_path):
    """Гонка recover vs. браузер: карантин успел раньше, доказательство пришло позже.

    recover_stale_attempts переводит протухшую `clicking`-попытку в `unknown`. Если
    браузер после этого вернул ПОЛНОЕ доказательство, оно обязано быть записано:
    иначе finalize_confirmed промахивается по status, finalize_unknown промахивается
    следом, и confirmation_url + скриншот + хеш не сохраняются нигде. Направление
    ошибки безопасное, но выбрасывать доказанную подачу нельзя.
    """
    conn, _schema = db_schema
    apply_migrations(conn)
    aid, attempt_id = _clicking_attempt(conn)
    with conn.cursor() as cur:
        cur.execute("update submission_attempt set lease_until=now() - interval '1 hour' "
                    "where attempt_id=%s", (attempt_id,))
    conn.commit()
    assert store.recover_stale_attempts(conn)["quarantined"] == 1
    conn.commit()
    assert _states(conn, aid, attempt_id) == ("submit_unknown", "unknown")

    shot = tmp_path / "confirm.png"
    shot.write_bytes(b"png-bytes")
    result = _full_proof()
    result.screenshot_path = str(shot)

    assert store.finalize_confirmed(conn, attempt_id, result) is True
    conn.commit()
    assert _states(conn, aid, attempt_id) == ("submitted", "confirmed")
    with conn.cursor() as cur:
        cur.execute(
            "select payload_json from event where event_type='application.submitted' "
            "and entity_id=%s", (aid,))
        payload = cur.fetchone()[0]
    assert payload["confirmation_url"] == "https://boards.example/jobs/1/confirmation"
    assert payload["screenshot_sha256"]


@pytest.mark.db
def test_human_source_still_cannot_confirm_a_live_clicking_attempt(db_schema, tmp_path):
    """Человеческое разрешение остаётся ровно тем, чем было: подъёмом из unknown.

    Живая `clicking`-попытка — зона браузера, а не ручного вердикта; расширение
    Находки 3 касается только автоматического источника.
    """
    conn, _schema = db_schema
    apply_migrations(conn)
    aid, attempt_id = _clicking_attempt(conn)
    shot = tmp_path / "confirm.png"
    shot.write_bytes(b"png-bytes")
    result = _full_proof()
    result.screenshot_path = str(shot)

    assert store.finalize_confirmed(conn, attempt_id, result,
                                    resolution_source="human") is False
    conn.commit()
    assert _states(conn, aid, attempt_id) == ("submitting", "clicking")


@pytest.mark.db
def test_not_submitted_after_click_becomes_unknown(db_schema):
    conn, _schema = db_schema
    apply_migrations(conn)
    aid, attempt_id = _clicking_attempt(conn)

    assert store.finalize_not_submitted(
        conn, attempt_id, SubmitResult(click_performed=True),
        "no_confirmation") is True
    conn.commit()
    assert _states(conn, aid, attempt_id) == ("submit_unknown", "unknown")


@pytest.mark.db
def test_unknown_is_recorded_with_reason(db_schema):
    conn, _schema = db_schema
    apply_migrations(conn)
    aid, attempt_id = _clicking_attempt(conn)

    assert store.finalize_unknown(
        conn, attempt_id, SubmitResult(click_performed=True),
        "no_confirmation") is True
    conn.commit()
    with conn.cursor() as cur:
        cur.execute("select failure_signal from submission_attempt where attempt_id=%s",
                    (attempt_id,))
        assert cur.fetchone()[0] == "no_confirmation"
