import csv

import pytest

from job_machine.db import migrate
from job_machine.mcp import tools
from job_machine.runtime import control as runtime_control


def _apply(conn):
    for m in migrate.pending(migrate.discover_migrations("db/migrations"),
                             migrate.applied_migrations(conn)):
        migrate.apply_migration(conn, m)


def _write_manifest(path, aid, resume_path, resume_hash):
    """Записать валидный PackageManifest на диск (его читает submit/_submit_one)."""
    from job_machine.package.models import PackageManifest, ResumeArtifact
    m = PackageManifest(
        application_id=aid, company="Acme", role="QA Lead",
        destination_url="https://acme/apply",
        resume=ResumeArtifact(filename="cv.pdf", path=resume_path,
                              content_hash=resume_hash),
        answers=[], consents=[], warnings=[],
        answers_hash="ah", consents_hash="ch", payload_hash="ph1")
    path.write_text(m.model_dump_json(), encoding="utf-8")


def _seed_pre_submit_ready(conn, tmp_path):
    import hashlib
    summary_file = tmp_path / "disclosed-summary.ru.md"
    summary_file.write_text("Компания: Acme", encoding="utf-8")
    # content_hash — реальный sha256 байтов файла: показ сводки fail-closed (аудит 02.07)
    summary_hash = hashlib.sha256(summary_file.read_bytes()).hexdigest()
    manifest_file = tmp_path / "manifest.json"
    # реальное резюме, привязанное к пакету (§3 resume safety: submit без него блокируется)
    resume_file = tmp_path / "cv.pdf"
    resume_file.write_bytes(b"%PDF integration resume")
    resume_hash = hashlib.sha256(resume_file.read_bytes()).hexdigest()
    with conn.cursor() as cur:
        cur.execute("insert into vacancy (company, title, canonical_url, ats_family, "
                    "state) values ('Acme','QA Lead','https://acme/apply','greenhouse',"
                    "'triaged') returning vacancy_id")
        vid = cur.fetchone()[0]
        cur.execute("insert into application (vacancy_id, candidate_id, state, payload_hash) "
                    "values (%s,'andrey-s','pre_submit_ready','ph1') returning application_id",
                    (vid,))
        aid = str(cur.fetchone()[0])
        _write_manifest(manifest_file, aid, str(resume_file), resume_hash)
        cur.execute("insert into artifact (application_id, artifact_type, path_or_uri, "
                    "content_hash) values (%s,'approval_summary',%s,%s)",
                    (aid, str(summary_file), summary_hash))
        cur.execute("insert into artifact (application_id, artifact_type, path_or_uri, "
                    "content_hash) values (%s,'manifest',%s,'mh')",
                    (aid, str(manifest_file)))
        cur.execute("insert into artifact (application_id, artifact_type, path_or_uri, "
                    "content_hash) values (%s,'resume',%s,%s) returning artifact_id",
                    (aid, str(resume_file), resume_hash))
        rid = cur.fetchone()[0]
        cur.execute("update application set resume_artifact_id=%s where application_id=%s",
                    (rid, aid))
        cur.execute("insert into event (entity_type, entity_id, event_type, payload_json) "
                    "values ('application', %s, 'application.pre_submit_ready', "
                    "'{\"screenshot_path\": \"/art/shot.png\"}'::jsonb)", (aid,))
    return aid


class FakeBrowser:
    """Имитация SubmitBrowserClient: inspect без блокера, submit с confirmation.

    confirm_screenshot_path — реальный файл под pytest tmp_path (см. вызывающий
    тест): подчищается фикстурой автоматически, в отличие от tempfile.mkstemp.
    """
    def __init__(self, confirm_screenshot_path):
        self._confirm_screenshot_path = confirm_screenshot_path

    def create_session(self): return "sid"
    def inspect(self, sid, url):
        from job_machine.browser.schema import FormSchema, InspectResult
        return InspectResult(blocker=None, form_schema=FormSchema(url=url),
                             screenshot_path="/art/shot.png")
    def submit(self, sid, fields, resume_path=None, consent_checks=None):
        from job_machine.browser.schema import SubmitResult
        # Полный набор доказательных полей (T4/T8): submission_proof_missing
        # засчитывает только click_performed+confirmation_signal+form_absent+
        # errors_absent+screenshot_path все вместе — иначе finalize_confirmed
        # не сработает и подача уйдёт в submit_unknown вместо submitted.
        # screenshot_path обязан указывать на реально существующий непустой
        # файл: finalize_confirmed хеширует его с диска (_screenshot_sha256),
        # фиктивный путь без файла тоже даёт submit_unknown.
        self._confirm_screenshot_path.write_bytes(b"fake-png-bytes")
        return SubmitResult(submitted=True, click_performed=True,
                            confirmation_url="https://acme/thanks",
                            confirmation_signal="confirmation_url",
                            form_absent=True, errors_absent=True,
                            screenshot_path=str(self._confirm_screenshot_path))
    def dispose(self, sid): pass


class LocalWorker:
    """In-process стенд job-submit воркера: submit_one/get_application_detail зовут
    НАСТОЯЩИЕ service.run_submit_one / store.load_application_detail против реального conn.
    Шов делегирования тот же, что в проде; HTTP-граница покрыта отдельными тестами."""
    def __init__(self, conn, browser):
        self._conn, self._browser = conn, browser

    def submit_one(self, application_id):
        from job_machine.submit import service
        return service.run_submit_one(self._conn, self._browser, application_id)

    def get_application_detail(self, application_id):
        from job_machine.mcp import store
        return store.load_application_detail(self._conn, application_id)


@pytest.mark.db
def test_full_loop_list_approve_submit(db_schema, tmp_path):
    conn, _ = db_schema
    _apply(conn)
    aid = _seed_pre_submit_ready(conn, tmp_path)
    conn.commit()

    worker = LocalWorker(conn, FakeBrowser(tmp_path / "confirm.png"))

    queue = tools.list_ready(conn, "andrey-s", limit=10)
    assert any(r["application_id"] == aid for r in queue)

    detail = tools.get_application(worker, aid)
    assert "Компания: Acme" in detail["summary_md"]

    appr = tools.request_approval(conn, aid)
    assert appr["payload_hash"] == "ph1"
    assert tools.approve_application(conn, aid)["approved"] is True

    # Рубильник подачи fail-closed по умолчанию (миграция 0024): без явного
    # включения claim не возьмёт даже одобренную заявку. Включаем здесь, чтобы
    # тест проверял сквозной путь, а не срабатывание защиты.
    assert runtime_control.set_submit_enabled(conn, True, actor="test") is True
    conn.commit()

    csv_path = str(tmp_path / "audit" / "submissions.csv")
    out = tools.submit_application(conn, worker, aid, csv_path=csv_path)
    assert out["submitted"] == 1            # достоверно: одна заявка подана
    assert out["status"] == "submitted"     # application.state перешёл в submitted
    assert out["funnel_recorded"] is True   # автозапись audit-строки из БД
    # Регресс: confirmation_url пропадал из payload события application.submitted
    # (finalize_confirmed эмитил только attempt_id/signal/hash), поэтому и
    # submit_application (читает через load_submit_confirmation), и CSV-аудит
    # теряли реальный URL подтверждения — FakeBrowser.submit возвращает конкретный.
    assert out["confirmation_url"] == "https://acme/thanks"

    rec = tools.record_outcome(conn, aid, csv_path=csv_path)
    assert rec["recorded"] is True
    assert rec["already_recorded"] is True  # идемпотентно после автозаписи

    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    assert rows[0]["application_id"] == aid
    assert rows[0]["confirmation_url"] == "https://acme/thanks"
