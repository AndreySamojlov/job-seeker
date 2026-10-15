import pytest

from job_machine.browser.schema import FormSchema, InspectResult, SubmitResult
from job_machine.submit import service, store
from tests.conftest import apply_migrations
from tests.submit.test_claim import _approved_application


class FakeBrowser:
    """Браузер, который отвечает заранее заданным результатом submit."""

    def __init__(self, submit_result, url="https://boards.example/jobs/1"):
        self.submit_result = submit_result
        self.url = url
        self.submit_calls = 0

    def create_session(self):
        return "sid"

    def inspect(self, sid, url):
        return InspectResult(blocker=None, form_schema=FormSchema(url=self.url, fields=[]))

    def submit(self, sid, fields, resume_path=None, consent_checks=None):
        self.submit_calls += 1
        return self.submit_result

    def dispose(self, sid):
        return None


@pytest.fixture
def prepared(db_schema, tmp_path, monkeypatch):
    conn, _schema = db_schema
    apply_migrations(conn)
    aid = _approved_application(conn)

    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"pdf")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text("{}", encoding="utf-8")

    with conn.cursor() as cur:
        cur.execute(
            "insert into artifact (application_id, artifact_type, path_or_uri, "
            "content_hash) values (%s,'manifest',%s,'mh') returning artifact_id",
            (aid, str(manifest_path)))
        cur.execute(
            "insert into artifact (application_id, artifact_type, path_or_uri, "
            "content_hash) values (%s,'resume',%s,%s) returning artifact_id",
            (aid, str(resume), "rh"))
        resume_artifact_id = cur.fetchone()[0]
        cur.execute("update application set resume_artifact_id=%s where application_id=%s",
                    (resume_artifact_id, aid))
    conn.commit()

    class FakeManifest:
        payload_hash = "ph1"
        destination_url = "https://boards.example/jobs/1"
        answers: dict = {}
        consents: dict = {}

    monkeypatch.setattr(service, "_load_manifest", lambda path: FakeManifest())
    monkeypatch.setattr(service, "map_fields",
                        lambda *a, **k: type("M", (), {
                            "unmatched_required": [], "fields": {}, "auto_consents": {}})())
    monkeypatch.setattr(service.gate, "check_submit_gate", lambda *a, **k: None)
    monkeypatch.setattr(service.gate, "check_resume_hash_gate", lambda **k: None)
    monkeypatch.setattr(service, "hash_file", lambda path: "rh")
    return conn, aid


@pytest.mark.db
def test_browser_says_not_submitted_lands_in_unknown(prepared):
    conn, aid = prepared
    browser = FakeBrowser(SubmitResult(submitted=False, click_performed=True,
                                       failure_signal="no_confirmation"))

    summary = service.run_submit_one(conn, browser, aid)

    assert summary.submitted == 0
    with conn.cursor() as cur:
        cur.execute("select state from application where application_id=%s", (aid,))
        assert cur.fetchone()[0] == "submit_unknown"


def _expire_lease(conn, attempt_id):
    with conn.cursor() as cur:
        cur.execute("update submission_attempt set lease_until=now() - interval '1 hour' "
                    "where attempt_id=%s", (attempt_id,))
    conn.commit()


def _full_proof(screenshot_path):
    return SubmitResult(
        submitted=True, click_performed=True,
        confirmation_url="https://boards.example/jobs/1/confirmation",
        confirmation_signal="confirmation_url", form_absent=True,
        errors_absent=True, screenshot_path=str(screenshot_path))


@pytest.mark.db
def test_run_submit_recovers_stale_lease_before_claiming(prepared, tmp_path):
    """Воркер умер после claim — заявка висит в submitting с протухшим лизом.

    recover_stale_attempts вызывающих не имела: /submit/recover никто не дёргал,
    и такая заявка не возвращалась в очередь никогда. Штатный прогон подачи обязан
    сам расклинить её ДО того, как брать новую работу.
    """
    conn, aid = prepared
    dead = store.claim_application(conn, aid, worker_id="dead-worker")
    conn.commit()
    _expire_lease(conn, dead["attempt_id"])

    shot = tmp_path / "confirm.png"
    shot.write_bytes(b"png-bytes")
    browser = FakeBrowser(_full_proof(shot))

    summary = service.run_submit(conn, browser, limit=5)

    assert summary.submitted == 1
    with conn.cursor() as cur:
        cur.execute("select state from application where application_id=%s", (aid,))
        assert cur.fetchone()[0] == "submitted"
        cur.execute("select status, failure_signal from submission_attempt "
                    "where attempt_id=%s", (dead["attempt_id"],))
        assert cur.fetchone() == ("failed", "lease_expired")


@pytest.mark.db
def test_run_submit_one_recovers_stale_lease_before_claiming(prepared, tmp_path):
    """Per-id путь кокпита — та же гарантия: владелец повторяет подачу заявки,
    зависшей на умершем воркере, и она не должна оставаться незаклеймленной."""
    conn, aid = prepared
    dead = store.claim_application(conn, aid, worker_id="dead-worker")
    conn.commit()
    _expire_lease(conn, dead["attempt_id"])

    shot = tmp_path / "confirm.png"
    shot.write_bytes(b"png-bytes")
    browser = FakeBrowser(_full_proof(shot))

    summary = service.run_submit_one(conn, browser, aid)

    assert summary.submitted == 1
    with conn.cursor() as cur:
        cur.execute("select state from application where application_id=%s", (aid,))
        assert cur.fetchone()[0] == "submitted"


@pytest.mark.db
def test_unclosable_attempt_is_audited_not_committed_silently(prepared, monkeypatch,
                                                              tmp_path):
    """Лиз протух и recover уже закрыл попытку, пока воркер был в полёте.

    fail_claimed_attempt пишет только по status='claimed' — здесь она промахнётся и
    вернёт False. Раньше это значение игнорировалось и транзакция коммитилась молча:
    ни в состоянии, ни в аудите не оставалось следа, что попытку закрыть не удалось.
    """
    conn, aid = prepared

    def _die_after_recovery(path):
        with conn.cursor() as cur:
            cur.execute("update submission_attempt set "
                        "lease_until=now() - interval '1 hour' where status='claimed'")
        conn.commit()
        store.recover_stale_attempts(conn)
        conn.commit()
        raise RuntimeError("worker died mid-flight")

    monkeypatch.setattr(service, "_load_manifest", _die_after_recovery)
    browser = FakeBrowser(_full_proof(tmp_path / "unused.png"))

    summary = service.run_submit_one(conn, browser, aid)

    assert summary.errors == 1
    assert browser.submit_calls == 0
    with conn.cursor() as cur:
        cur.execute("select payload_json from event where entity_id=%s "
                    "and event_type='application.submit_attempt_orphaned'", (aid,))
        row = cur.fetchone()
    assert row is not None, "промах fail_claimed_attempt должен быть виден в аудите"
    assert row[0]["blocker"] == "broken_flow"


@pytest.mark.db
def test_submit_is_attempted_at_most_once(prepared):
    conn, aid = prepared
    browser = FakeBrowser(SubmitResult(submitted=False, click_performed=True,
                                       failure_signal="no_confirmation"))

    service.run_submit_one(conn, browser, aid)
    service.run_submit_one(conn, browser, aid)

    assert browser.submit_calls == 1
