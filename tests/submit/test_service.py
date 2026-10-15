import tempfile
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from job_machine.db import migrate
from job_machine.runtime import control
from job_machine.submit import service, store


def _apply(conn):
    for m in migrate.pending(migrate.discover_migrations("db/migrations"),
                             migrate.applied_migrations(conn)):
        migrate.apply_migration(conn, m)


def _seed_app(conn, payload_hash="ph1", resume_content_hash="resumehash",
             state="approved"):
    """[Task 10] state по умолчанию 'approved' — жизненный цикл клеймит заявку из
    этого состояния (claim_next/claim_application), а не из 'pre_submit_ready'
    (снятый pull_approved-контракт)."""
    with conn.cursor() as cur:
        cur.execute(
            "insert into vacancy (company, title, canonical_url, ats_family, "
            "vacancy_status, state) values ('Acme','QA Lead','https://acme/svc','greenhouse',"
            "'triaged','triaged') returning vacancy_id")
        vid = cur.fetchone()[0]
        cur.execute(
            "insert into application (vacancy_id, candidate_id, verdict, package_status, "
            "state, payload_hash) "
            "values (%s,'andrey-s','apply','none',%s,%s) "
            "returning application_id",
            (vid, state, payload_hash))
        aid = cur.fetchone()[0]
        cur.execute(
            "insert into artifact (application_id, artifact_type, path_or_uri) "
            "values (%s,'manifest','/data/applications/acme-qa-lead/manifest.json')",
            (aid,))
        cur.execute(
            "insert into artifact (application_id, artifact_type, path_or_uri, content_hash) "
            "values (%s,'resume','/data/resumes/x/resume.pdf',%s) returning artifact_id",
            (aid, resume_content_hash))
        resume_art_id = cur.fetchone()[0]
        cur.execute(
            "update application set resume_artifact_id=%s where application_id=%s",
            (resume_art_id, aid))
        return str(aid)


def _seed_approval(conn, application_id, payload_hash="ph1", hours_offset=24):
    expires = datetime.now(tz=timezone.utc) + timedelta(hours=hours_offset)
    with conn.cursor() as cur:
        cur.execute(
            "insert into approval (application_id, approval_type, payload_hash, "
            "approval_status, approval_token, expires_at, approved_at) "
            "values (%s,'submit',%s,'approved','tok64',%s,%s)",
            (uuid.UUID(application_id), payload_hash, expires,
             datetime.now(tz=timezone.utc)))
    # [Task 10] claim_next/claim_application читают рубильник fail-closed —
    # без явного включения claim всегда вернёт None.
    control.set_submit_enabled(conn, True, actor="test")


class _ManifestStub:
    destination_url = "https://boards.greenhouse.io/acme/jobs/1"
    answers = []
    consents = []
    ats_family = "greenhouse"
    payload_hash = "ph1"  # совпадает с application.payload_hash сида (_seed_app)


class _InspectOk:
    blocker = None

    class form_schema:
        url = "https://job-boards.greenhouse.io/acme/jobs/1"  # same post, другой хост
        fields = []
        file_inputs = []
        consent_checkboxes = []
        submit_buttons = []


def _write_temp_screenshot() -> str:
    """[Task 10] finalize_confirmed хеширует физический файл (submission_proof_missing) —
    'unmatched' и '/tmp/confirm.png'-заглушки старого контракта больше не сходят с рук;
    нужен реально существующий непустой файл на диске."""
    fd, path = tempfile.mkstemp(suffix=".png")
    with open(fd, "wb") as fh:
        fh.write(b"fake-screenshot-bytes")
    return path


_SCREENSHOT_PATH = _write_temp_screenshot()


class _SubmitOk:
    """[Task 10] Полное долговечное доказательство подачи (submission_proof_missing):
    click_performed + confirmation_signal + form_absent + errors_absent + screenshot_path
    реального файла — иначе finalize_confirmed честно отказывается засчитать submitted."""
    submitted = True
    click_performed = True
    confirmation_url = "https://job-boards.greenhouse.io/acme/jobs/1/confirmation"
    confirmation_signal = "confirmation_url"
    form_absent = True
    errors_absent = True
    screenshot_path = _SCREENSHOT_PATH
    unmatched = []
    failure_signal = None


class _StubBrowser:
    def __init__(self):
        self.submitted = []

    def create_session(self): return "s1"

    def inspect(self, sid, url):
        return _InspectOk()

    def fill(self, sid, fields, resume_path=None):
        from job_machine.browser.schema import FillResult
        return FillResult(filled=[], stopped_before_submit=True)

    def submit(self, sid, fields, resume_path=None, consent_checks=None):
        self.submitted.append(sid)
        return _SubmitOk()

    def dispose(self, sid): pass

    def close(self): pass


@pytest.mark.db
def test_run_submit_submits_and_records(tmp_path, db_schema, monkeypatch):
    conn, _ = db_schema
    _apply(conn)
    aid = _seed_app(conn, resume_content_hash="resumehash")
    conn.commit()
    _seed_approval(conn, aid)
    conn.commit()

    import job_machine.submit.service as svc_mod
    monkeypatch.setattr(svc_mod, "_load_manifest", lambda path: _ManifestStub())
    monkeypatch.setattr(svc_mod, "hash_file", lambda path: "resumehash")

    browser = _StubBrowser()
    summary = service.run_submit(conn, browser, limit=10)
    assert summary.submitted == 1
    assert summary.errors == 0
    assert len(browser.submitted) == 1

    with conn.cursor() as cur:
        cur.execute("select state from application where application_id=%s", (uuid.UUID(aid),))
        assert cur.fetchone()[0] == "submitted"


@pytest.mark.db
def test_run_submit_blocks_when_browser_reports_not_submitted(tmp_path, db_schema, monkeypatch):
    """Живой инцидент 23.07.2026: браузер-воркер сам обнаружил, что клик по submit
    не прошёл (required-поле пусто/:invalid после клика, или locator не найден) —
    submit-сервис не должен писать state=submitted поверх этого факта. 145+ заявок
    ушли в БД как submitted, хотя submit_confirm.png показывал форму с ошибками
    валидации, потому что раньше submit_result.submitted игнорировался целиком.

    [Task 10] Обновлено под новый жизненный цикл: клик уже начат к этому моменту
    (mark_clicking пересечён), поэтому возврат в очередь/submit_blocked запрещён
    инвариантом — исход неизвестен и заявка уходит в submit_unknown, а не в
    submit_blocked/submit_not_confirmed."""
    conn, _ = db_schema
    _apply(conn)
    aid = _seed_app(conn, resume_content_hash="resumehash")
    conn.commit()
    _seed_approval(conn, aid)
    conn.commit()
    import job_machine.submit.service as svc_mod
    monkeypatch.setattr(svc_mod, "_load_manifest", lambda path: _ManifestStub())
    monkeypatch.setattr(svc_mod, "hash_file", lambda path: "resumehash")

    class _NotSubmitted(_SubmitOk):
        """Доказательство НЕ полно (клик был, подтверждения нет) — иначе
        finalize_confirmed засчитал бы submitted вопреки .submitted=False."""
        submitted = False
        confirmation_signal = None
        form_absent = False
        errors_absent = False
        unmatched = ["work_authorization"]
        failure_signal = "unmatched"

    class _NotSubmittedBrowser(_StubBrowser):
        def submit(self, sid, fields, resume_path=None, consent_checks=None):
            self.submitted.append(sid)
            return _NotSubmitted()

    browser = _NotSubmittedBrowser()
    summary = service.run_submit(conn, browser, limit=10)
    assert summary.submitted == 0
    assert summary.blocked == 1
    assert len(browser.submitted) == 1  # клик реально пробовали — просто не прошёл

    with conn.cursor() as cur:
        cur.execute("select state, current_blocker from application where application_id=%s",
                    (uuid.UUID(aid),))
        assert cur.fetchone() == ("submit_unknown", "submit_unknown")


@pytest.mark.db
def test_run_submit_blocks_on_resume_hash_mismatch(tmp_path, db_schema, monkeypatch):
    conn, _ = db_schema
    _apply(conn)
    aid = _seed_app(conn, resume_content_hash="original_hash")
    conn.commit()
    _seed_approval(conn, aid)
    conn.commit()

    import job_machine.submit.service as svc_mod
    monkeypatch.setattr(svc_mod, "_load_manifest", lambda path: _ManifestStub())
    monkeypatch.setattr(svc_mod, "hash_file", lambda path: "tampered_hash")

    browser = _StubBrowser()
    summary = service.run_submit(conn, browser, limit=10)
    assert summary.submitted == 0
    assert summary.blocked == 1
    assert len(browser.submitted) == 0

    with conn.cursor() as cur:
        cur.execute("select state from application where application_id=%s", (uuid.UUID(aid),))
        assert cur.fetchone()[0] == "submit_blocked"
        # Леджер попыток обязан сохранить настоящую причину, а не схлопнуть её в
        # broken_flow: имя гарда есть в allowlist safe_failure_code.
        cur.execute("select failure_signal from submission_attempt "
                    "where application_id=%s", (uuid.UUID(aid),))
        assert cur.fetchone()[0] == "NoResumeUploadWithoutHashMatch"


@pytest.mark.db
def test_run_submit_guard_blocks_expired(tmp_path, db_schema):
    conn, _ = db_schema
    _apply(conn)
    aid = _seed_app(conn)
    conn.commit()
    _seed_approval(conn, aid, hours_offset=-1)
    conn.commit()
    summary = service.run_submit(conn, _StubBrowser(), limit=10)
    assert summary.submitted == 0
    assert summary.pulled == 0   # claim_next filtered it out (expired approval)


@pytest.mark.db
def test_run_submit_isolates_browser_exception(tmp_path, db_schema, monkeypatch):
    conn, _ = db_schema
    _apply(conn)
    aid = _seed_app(conn)
    conn.commit()
    _seed_approval(conn, aid)
    conn.commit()

    import job_machine.submit.service as svc_mod
    monkeypatch.setattr(svc_mod, "_load_manifest",
                        lambda path: _ManifestStub())

    class _BrokenBrowser(_StubBrowser):
        def submit(self, sid, fields, resume_path=None):
            raise RuntimeError("network error")

    summary = service.run_submit(conn, _BrokenBrowser(), limit=10)
    assert summary.errors == 1
    assert summary.submitted == 0
    with conn.cursor() as cur:
        cur.execute("select state from application where application_id=%s", (uuid.UUID(aid),))
        assert cur.fetchone()[0] == "submit_blocked"


@pytest.mark.db
def test_submit_blocks_on_manifest_payload_hash_mismatch(tmp_path, db_schema, monkeypatch):
    """Submit исполняет РОВНО одобренный payload: manifest-файл обязан нести тот же
    payload_hash, что одобрен в БД (ревью среза: stale/перезаписанный манифест)."""
    conn, _ = db_schema
    _apply(conn)
    aid = _seed_app(conn, resume_content_hash="resumehash")
    conn.commit()
    _seed_approval(conn, aid)
    conn.commit()
    import job_machine.submit.service as svc_mod

    class _StaleManifest(_ManifestStub):
        payload_hash = "STALE_PH"

    monkeypatch.setattr(svc_mod, "_load_manifest", lambda path: _StaleManifest())
    monkeypatch.setattr(svc_mod, "hash_file", lambda path: "resumehash")
    browser = _StubBrowser()
    summary = service.run_submit(conn, browser, limit=10)
    assert summary.blocked == 1
    assert len(browser.submitted) == 0
    with conn.cursor() as cur:
        cur.execute("select state, current_blocker from application where application_id=%s",
                    (uuid.UUID(aid),))
        assert cur.fetchone() == ("submit_blocked", "manifest_integrity_mismatch")
        cur.execute("select failure_signal from submission_attempt "
                    "where application_id=%s", (uuid.UUID(aid),))
        assert cur.fetchone()[0] == "manifest_integrity_mismatch"


@pytest.mark.db
def test_claim_picks_newest_manifest(db_schema):
    """После fill-ребинда в БД две строки manifest — claim обязан взять новейшую.

    Раньше это проверялось через pull_approved_one; функция удалена вместе с
    остальным мёртвым pull-контрактом, а инвариант живёт в claim (_claim), поэтому
    тест бьёт по живому пути подачи."""
    conn, _ = db_schema
    _apply(conn)
    aid = _seed_app(conn)
    conn.commit()
    _seed_approval(conn, aid)
    conn.commit()
    with conn.cursor() as cur:
        cur.execute("insert into artifact (application_id, artifact_type, path_or_uri, "
                    "created_at) values (%s,'manifest','/data/rebound/manifest.json', "
                    "now() + interval '1 second')", (uuid.UUID(aid),))
    conn.commit()
    row = store.claim_application(conn, aid, worker_id="w1")
    assert row["manifest_path"] == "/data/rebound/manifest.json"


@pytest.mark.db
def test_submit_blocks_when_no_resume_bound(db_schema, monkeypatch):
    """Зеркало fill (§3 resume safety): заявка без привязанного резюме не доходит
    до браузера — явный broken_flow, а не тихий submit без resume-hash-гейта."""
    conn, _ = db_schema
    _apply(conn)
    with conn.cursor() as cur:
        cur.execute(
            "insert into vacancy (company, title, canonical_url, ats_family, "
            "vacancy_status, state) values ('Acme','QA','https://acme/nores','greenhouse',"
            "'triaged','triaged') returning vacancy_id")
        vid = cur.fetchone()[0]
        cur.execute(
            "insert into application (vacancy_id, candidate_id, verdict, package_status, "
            "state, payload_hash) values (%s,'andrey-s','apply','none','approved',"
            "'ph1') returning application_id", (vid,))
        aid = str(cur.fetchone()[0])
        cur.execute(
            "insert into artifact (application_id, artifact_type, path_or_uri) "
            "values (%s,'manifest','/data/x/manifest.json')", (aid,))
    conn.commit()
    _seed_approval(conn, aid)
    conn.commit()
    import job_machine.submit.service as svc_mod
    monkeypatch.setattr(svc_mod, "_load_manifest", lambda path: _ManifestStub())
    browser = _StubBrowser()
    summary = service.run_submit(conn, browser, limit=10)
    assert summary.blocked == 1
    assert len(browser.submitted) == 0
    with conn.cursor() as cur:
        cur.execute("select state, current_blocker from application where application_id=%s",
                    (uuid.UUID(aid),))
        assert cur.fetchone() == ("submit_blocked", "broken_flow")


@pytest.mark.db
def test_submit_blocks_when_redirected_to_other_post(tmp_path, db_schema, monkeypatch):
    conn, _ = db_schema
    _apply(conn)
    aid = _seed_app(conn, resume_content_hash="resumehash")
    conn.commit()
    _seed_approval(conn, aid)
    conn.commit()
    import job_machine.submit.service as svc_mod
    monkeypatch.setattr(svc_mod, "_load_manifest", lambda path: _ManifestStub())
    monkeypatch.setattr(svc_mod, "hash_file", lambda path: "resumehash")

    class _InspectRedirect(_InspectOk):
        class form_schema(_InspectOk.form_schema):
            url = "https://job-boards.greenhouse.io/acme/jobs/999"

    class _RedirectBrowser(_StubBrowser):
        def inspect(self, sid, url):
            return _InspectRedirect()

    browser = _RedirectBrowser()
    summary = service.run_submit(conn, browser, limit=10)
    assert summary.blocked == 1
    assert len(browser.submitted) == 0  # fail-closed до клика
    with conn.cursor() as cur:
        cur.execute("select state, current_blocker from application where application_id=%s",
                    (uuid.UUID(aid),))
        assert cur.fetchone() == ("submit_blocked", "destination_redirect")
        cur.execute("select failure_signal from submission_attempt "
                    "where application_id=%s", (uuid.UUID(aid),))
        assert cur.fetchone()[0] == "destination_redirect"


@pytest.mark.db
def test_post_submit_confirmation_mismatch_alerts(tmp_path, db_schema, monkeypatch):
    conn, _ = db_schema
    _apply(conn)
    aid = _seed_app(conn, resume_content_hash="resumehash")
    conn.commit()
    _seed_approval(conn, aid)
    conn.commit()
    import job_machine.submit.service as svc_mod
    monkeypatch.setattr(svc_mod, "_load_manifest", lambda path: _ManifestStub())
    monkeypatch.setattr(svc_mod, "hash_file", lambda path: "resumehash")

    class _MismatchSubmit(_SubmitOk):
        confirmation_url = "https://job-boards.greenhouse.io/acme/jobs/777"

    class _MismatchBrowser(_StubBrowser):
        def submit(self, sid, fields, resume_path=None, consent_checks=None):
            return _MismatchSubmit()

    summary = service.run_submit(conn, _MismatchBrowser(), limit=10)
    assert summary.submitted == 1  # submit состоялся — факт не отменить
    with conn.cursor() as cur:
        cur.execute("select state, current_blocker from application where application_id=%s",
                    (uuid.UUID(aid),))
        assert cur.fetchone() == ("submitted", "destination_mismatch")
        cur.execute("select payload_json from event where entity_id=%s "
                    "and event_type='application.submit_destination_mismatch'",
                    (uuid.UUID(aid),))
        p = cur.fetchone()[0]
        assert p["confirmation_url"].endswith("/jobs/777")


@pytest.mark.db
def test_post_submit_generic_thanks_url_no_false_alert(tmp_path, db_schema, monkeypatch):
    """Страница благодарности generic-ATS не идентифицирует пост — алерт был бы
    шумом на каждом не-greenhouse сабмите; пред-submit гейт destination уже отработал."""
    conn, _ = db_schema
    _apply(conn)
    aid = _seed_app(conn, resume_content_hash="resumehash")
    conn.commit()
    _seed_approval(conn, aid)
    conn.commit()
    import job_machine.submit.service as svc_mod
    monkeypatch.setattr(svc_mod, "_load_manifest", lambda path: _ManifestStub())
    monkeypatch.setattr(svc_mod, "hash_file", lambda path: "resumehash")

    class _ThanksSubmit(_SubmitOk):
        confirmation_url = "https://acme.example/thanks"

    class _ThanksBrowser(_StubBrowser):
        def submit(self, sid, fields, resume_path=None, consent_checks=None):
            return _ThanksSubmit()

    summary = service.run_submit(conn, _ThanksBrowser(), limit=10)
    assert summary.submitted == 1
    with conn.cursor() as cur:
        cur.execute("select current_blocker from application where application_id=%s",
                    (uuid.UUID(aid),))
        assert cur.fetchone()[0] is None  # generic thanks-URL — без ложного алерта


@pytest.mark.db
def test_post_submit_none_confirmation_skips_check(tmp_path, db_schema, monkeypatch):
    conn, _ = db_schema
    _apply(conn)
    aid = _seed_app(conn, resume_content_hash="resumehash")
    conn.commit()
    _seed_approval(conn, aid)
    conn.commit()
    import job_machine.submit.service as svc_mod
    monkeypatch.setattr(svc_mod, "_load_manifest", lambda path: _ManifestStub())
    monkeypatch.setattr(svc_mod, "hash_file", lambda path: "resumehash")

    class _NoneSubmit(_SubmitOk):
        confirmation_url = None

    class _NoneBrowser(_StubBrowser):
        def submit(self, sid, fields, resume_path=None, consent_checks=None):
            return _NoneSubmit()

    service.run_submit(conn, _NoneBrowser(), limit=10)
    with conn.cursor() as cur:
        cur.execute("select current_blocker from application where application_id=%s",
                    (uuid.UUID(aid),))
        assert cur.fetchone()[0] is None  # сравнивать нечего — без ложного алерта
