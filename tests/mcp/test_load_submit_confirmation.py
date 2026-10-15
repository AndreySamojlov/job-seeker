"""load_submit_confirmation обязан вернуть настоящий confirmation_url, а не путь
к файлу подтверждения (регресс: артефакт 'confirmation' хранит screenshot_path
и в record_submitted, и в finalize_confirmed — фолбэк на него подсовывал файловый
путь под видом URL, если событие не несло confirmation_url)."""
import pytest

from job_machine.browser.schema import SubmitResult
from job_machine.mcp import store as mcp_store
from job_machine.submit import store as submit_store
from tests.conftest import apply_migrations
from tests.submit.test_claim import _approved_application


@pytest.mark.db
def test_load_submit_confirmation_returns_url_not_screenshot_path(db_schema, tmp_path):
    conn, _schema = db_schema
    apply_migrations(conn)
    aid = _approved_application(conn)
    claim = submit_store.claim_application(conn, aid, worker_id="w1")
    conn.commit()
    submit_store.mark_clicking(conn, claim["attempt_id"])
    conn.commit()

    shot = tmp_path / "confirm.png"
    shot.write_bytes(b"png-bytes")
    result = SubmitResult(
        submitted=True,
        click_performed=True,
        confirmation_url="https://boards.example/jobs/1/confirmation",
        confirmation_signal="confirmation_url",
        form_absent=True,
        errors_absent=True,
        screenshot_path=str(shot),
    )
    assert submit_store.finalize_confirmed(conn, claim["attempt_id"], result) is True
    conn.commit()

    conf = mcp_store.load_submit_confirmation(conn, aid)
    assert conf["status"] == "submitted"
    assert conf["confirmation_url"] == "https://boards.example/jobs/1/confirmation"
    # Дефект: без фикса сюда мог утечь путь к PNG-файлу артефакта 'confirmation'.
    assert not conf["confirmation_url"].endswith(".png")
    assert str(shot) != conf["confirmation_url"]


@pytest.mark.db
def test_load_submit_confirmation_no_event_returns_none_not_artifact_path(db_schema):
    """Если по каким-то причинам события submitted с confirmation_url нет, функция
    обязана честно вернуть None, а не подсунуть путь к файлу артефакта 'confirmation'
    как будто это URL."""
    conn, _schema = db_schema
    apply_migrations(conn)
    with conn.cursor() as cur:
        cur.execute("insert into candidate (candidate_id, name) "
                    "values ('andrey-s','Andrey') on conflict do nothing")
        cur.execute("insert into vacancy (canonical_url, ats_family) values "
                    "('https://boards.example/jobs/2','greenhouse') returning vacancy_id")
        vid = cur.fetchone()[0]
        cur.execute("insert into application (vacancy_id, candidate_id, state) "
                    "values (%s,'andrey-s','submitted') returning application_id", (vid,))
        aid = cur.fetchone()[0]
        cur.execute(
            "insert into artifact (application_id, artifact_type, path_or_uri) "
            "values (%s,'confirmation',%s)", (aid, "/data/browser/x_confirm.png"))
    conn.commit()

    conf = mcp_store.load_submit_confirmation(conn, str(aid))
    assert conf["confirmation_url"] is None
