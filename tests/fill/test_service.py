import json
import uuid

import httpx
import pytest

from job_machine.browser.schema import FillResult, FormField, FormSchema, InspectResult
from job_machine.db import migrate
from job_machine.fill import service

pytestmark = pytest.mark.db

MANIFEST = {
    "application_id": "REPLACED", "company": "Acme", "role": "Eng",
    "destination_url": "https://boards.greenhouse.io/acme/jobs/1",
    "resume": {"filename": "r.pdf", "path": "RESUME_PATH", "content_hash": "RH"},
    "answers": [
        {"field": "Full name", "value": "Andrey Samoylov", "source": "locked"},
        {"field": "Email", "value": "a@b.com", "source": "locked"},
    ],
    "consents": [], "warnings": [],
    "answers_hash": "ah", "consents_hash": "ch", "payload_hash": "ph",
}


def test_run_fill_forwards_candidate_id_to_store(monkeypatch):
    """Fill-сервис прокидывает candidate_id в выборку fillable-очереди (проброс, без БД)."""
    captured = {}

    def fake_pull(conn, limit, candidate_id=None):
        captured["candidate_id"] = candidate_id
        return []

    monkeypatch.setattr(service.store, "pull_fillable", fake_pull)
    # run_fill теперь свипит протухшие агент-сессии первой строкой (Task 8) — с
    # object() вместо conn это упадёт на cursor(), поэтому свип тоже мокаем.
    monkeypatch.setattr(service, "sweep_agent_fill_timeouts", lambda conn, browser, timeout_minutes=None: 0)
    service.run_fill(object(), object(), limit=5, candidate_id="daria-b")
    assert captured["candidate_id"] == "daria-b"


class FakeBrowser:
    def __init__(self, inspect_result):
        self._inspect = inspect_result
        self.filled = None
        self.disposed = False
        self.released = None
        self.force_released = []
        self.retained = []
        self.last_session_id = None

    def create_session(self):
        self.last_session_id = "sid"
        return self.last_session_id

    def inspect(self, sid, url):
        return self._inspect

    def inspect_current(self, sid):
        return self._inspect

    def fill(self, sid, fields, resume_path=None, consent_checks=None):
        self.filled = fields
        return FillResult(filled=list(fields), resume_attached=True,
                          stopped_before_submit=True, unmatched=[])

    def dispose(self, sid):
        self.disposed = True

    def retain(self, sid):
        self.retained.append(sid)

    def release(self, sid):
        self.released = sid
        self.force_released.append(sid)


def _apply(conn):
    for m in migrate.pending(migrate.discover_migrations("db/migrations"),
                             migrate.applied_migrations(conn)):
        migrate.apply_migration(conn, m)
    conn.commit()


def _seed(conn, tmp_path, *, resume_bytes=b"%PDF resume", manifest_resume_hash=None,
          with_summary=True):
    import hashlib
    resume = tmp_path / "r.pdf"
    resume.write_bytes(resume_bytes)
    real_hash = hashlib.sha256(resume_bytes).hexdigest()
    manifest = dict(MANIFEST)
    manifest["resume"] = {"filename": "r.pdf", "path": str(resume),
                          "content_hash": manifest_resume_hash or real_hash}
    man_path = tmp_path / "manifest.json"
    man_path.write_text(json.dumps(manifest), encoding="utf-8")
    with conn.cursor() as cur:
        cur.execute("insert into vacancy (canonical_url, ats_family) "
                    "values ('https://x/1','greenhouse') returning vacancy_id")
        vid = cur.fetchone()[0]
        cur.execute("insert into application (vacancy_id, candidate_id, state) "
                    "values (%s,'andrey-s','package_ready') returning application_id", (vid,))
        aid = cur.fetchone()[0]
        cur.execute("insert into artifact (application_id, artifact_type, path_or_uri, "
                    "content_hash) values (%s,'resume',%s,%s) returning artifact_id",
                    (aid, str(resume), manifest["resume"]["content_hash"]))
        rid = cur.fetchone()[0]
        cur.execute("update application set resume_artifact_id=%s where application_id=%s",
                    (rid, aid))
        cur.execute("insert into artifact (application_id, artifact_type, path_or_uri, "
                    "content_hash) values (%s,'manifest',%s,'mh')", (aid, str(man_path)))
        if with_summary:
            cur.execute("insert into artifact (application_id, artifact_type, path_or_uri, "
                        "content_hash) values (%s,'approval_summary','/s.md','sh')", (aid,))
    conn.commit()
    # как в проде: manifest несёт РЕАЛЬНЫЙ application_id (его пишет package builder)
    manifest["application_id"] = str(aid)
    man_path.write_text(json.dumps(manifest), encoding="utf-8")
    return str(aid)


def _state(conn, aid):
    with conn.cursor() as cur:
        cur.execute("select state, current_blocker from application where application_id=%s",
                    (str(aid),))
        return cur.fetchone()


def test_happy_path_fills_and_marks_pre_submit_ready(db_schema, tmp_path):
    conn, _ = db_schema
    _apply(conn)
    aid = _seed(conn, tmp_path)
    schema = FormSchema(url=MANIFEST["destination_url"],
                        file_inputs=["job_application[resume]"], fields=[
        FormField(name="job_application[first_name]", field_type="text", required=True),
        FormField(name="job_application[last_name]", field_type="text", required=True),
        FormField(name="job_application[email]", field_type="email", required=True),
        FormField(name="job_application[resume]", field_type="file", required=True),
    ])
    browser = FakeBrowser(InspectResult(blocker=None, form_schema=schema))
    summary = service.run_fill(conn, browser, limit=10)
    assert summary.pre_submit_ready == 1
    assert _state(conn, aid) == ("pre_submit_ready", None)
    assert browser.filled["job_application[email]"] == "a@b.com"
    assert browser.disposed is True


def test_inspect_blocker_failclosed_blocks(db_schema, tmp_path):
    conn, _ = db_schema
    _apply(conn)
    aid = _seed(conn, tmp_path)
    browser = FakeBrowser(InspectResult(blocker="captcha", form_schema=None))
    summary = service.run_fill(conn, browser, limit=10)
    assert summary.blocked == 1
    assert _state(conn, aid) == ("fill_blocked", "captcha")
    assert browser.filled is None
    assert browser.disposed is True


def test_unknown_inspect_blocker_failclosed(db_schema, tmp_path):
    conn, _ = db_schema
    _apply(conn)
    aid = _seed(conn, tmp_path)
    browser = FakeBrowser(InspectResult(blocker="brand_new_wall", form_schema=None))
    service.run_fill(conn, browser, limit=10)
    assert _state(conn, aid) == ("fill_blocked", "brand_new_wall")


def test_vacancy_removed_blocks_and_marks_vacancy_stale(db_schema, tmp_path):
    conn, _ = db_schema
    _apply(conn)
    aid = _seed(conn, tmp_path)
    browser = FakeBrowser(InspectResult(blocker="vacancy_removed", form_schema=None))
    summary = service.run_fill(conn, browser, limit=10)
    assert summary.blocked == 1
    assert _state(conn, aid) == ("fill_blocked", "vacancy_removed")
    with conn.cursor() as cur:
        cur.execute(
            "select v.vacancy_status from application a join vacancy v "
            "on v.vacancy_id = a.vacancy_id where a.application_id=%s", (aid,))
        assert cur.fetchone()[0] == "stale"


def test_unmatched_required_hands_page_to_agent(db_schema, tmp_path):
    """Код не сопоставил required-поле → заявка не умирает mandatory_unknown,
    а переходит в agent_fill_pending, и сессия браузера остаётся жить (спека
    2026-08-06: mandatory_unknown больше не терминальный стоп на fill-стадии)."""
    conn, _ = db_schema
    _apply(conn)
    aid = _seed(conn, tmp_path)
    schema = FormSchema(url=MANIFEST["destination_url"],
                        file_inputs=["job_application[resume]"], fields=[
        FormField(name="job_application[email]", field_type="email", required=True),
        FormField(name="job_application[answers_attributes][0][text_value]", field_type="text",
                  label="Are you authorized to work in the EU?", required=True),
    ])
    browser = FakeBrowser(InspectResult(blocker=None, form_schema=schema))
    summary = service.run_fill(conn, browser, limit=1)
    assert summary.agent_fill_pending == 1
    assert summary.blocked == 0
    # Детерминированный проход отработал ДО передачи: агент получает страницу, где
    # сопоставленное уже стоит, а не пустую форму (живой прогон OKX 2026-08-07).
    assert browser.filled == {"job_application[email]": "a@b.com"}
    assert browser.retained == [browser.last_session_id]   # retain вызван
    assert browser.force_released == []                    # сессия НЕ освобождена
    assert _state(conn, aid) == ("agent_fill_pending", None)
    with conn.cursor() as cur:
        cur.execute("select agent_fill_session_id from application where application_id=%s",
                    (str(aid),))
        assert cur.fetchone()[0] == browser.last_session_id
    with conn.cursor() as cur:
        cur.execute("select count(*) from event where entity_id=%s "
                    "and event_type='application.agent_fill_pending'", (str(aid),))
        assert cur.fetchone()[0] == 1


@pytest.mark.parametrize('failure_stage', ['record','retain'])
def test_session_released_when_handoff_fails(db_schema, tmp_path, monkeypatch, failure_stage):
    """Сбой между retain и коммитом не должен оставить осиротевшую страницу:
    записи в БД нет, значит свип таймаутов её никогда не найдёт, а обычный dispose
    её не закроет — она жила бы до перезапуска воркера."""
    conn, _ = db_schema
    _apply(conn)
    aid = _seed(conn, tmp_path)
    schema = FormSchema(url=MANIFEST["destination_url"], fields=[
        FormField(name="job_application[answers_attributes][0][text_value]", field_type="text",
                  label="Are you authorized to work in the EU?", required=True),
    ])
    browser = FakeBrowser(InspectResult(blocker=None, form_schema=schema))

    def boom(*args, **kwargs):
        raise RuntimeError("db down")

    if failure_stage == 'record':
        monkeypatch.setattr(service.store, "record_agent_fill_pending", boom)
    else:
        def failed_retain(sid):
            browser.retained.append(sid)
            raise RuntimeError('retain acknowledgement lost')
        monkeypatch.setattr(browser,'retain',failed_retain)
    summary = service.run_fill(conn, browser, limit=1)

    assert summary.errors == 1
    assert browser.retained == ([browser.last_session_id] if failure_stage == 'retain' else [])
    assert browser.force_released == [browser.last_session_id]
    assert _state(conn, aid) == ("fill_blocked", "broken_flow")


def test_resume_hash_mismatch_blocks_via_guard(db_schema, tmp_path):
    conn, _ = db_schema
    _apply(conn)
    aid = _seed(conn, tmp_path, manifest_resume_hash="DELIBERATELY_WRONG")
    browser = FakeBrowser(InspectResult(blocker=None, form_schema=FormSchema(url="https://x/1")))
    service.run_fill(conn, browser, limit=10)
    state, blocker = _state(conn, aid)
    assert state == "fill_blocked"
    assert blocker == "NoResumeUploadWithoutHashMatch"


def test_missing_summary_blocks_via_guard(db_schema, tmp_path):
    conn, _ = db_schema
    _apply(conn)
    aid = _seed(conn, tmp_path, with_summary=False)
    browser = FakeBrowser(InspectResult(blocker=None, form_schema=FormSchema(url="https://x/1")))
    service.run_fill(conn, browser, limit=10)
    assert _state(conn, aid)[0] == "fill_blocked"
    assert _state(conn, aid)[1] == "NoFillBeforeDisclosedSummary"


def test_no_resume_bound_blocks(db_schema, tmp_path):
    # review MAJOR-2: заявка без привязанного резюме → явный broken_flow-стоп до hash,
    # а не замаскированный KeyError. Форму не трогаем.
    conn, _ = db_schema
    _apply(conn)
    with conn.cursor() as cur:
        cur.execute("insert into vacancy (canonical_url, ats_family) "
                    "values ('https://x/2','greenhouse') returning vacancy_id")
        vid = cur.fetchone()[0]
        cur.execute("insert into application (vacancy_id, candidate_id, state) "
                    "values (%s,'andrey-s','package_ready') returning application_id", (vid,))
        aid = cur.fetchone()[0]
        cur.execute("insert into artifact (application_id, artifact_type, path_or_uri, "
                    "content_hash) values (%s,'approval_summary','/s.md','sh')", (aid,))
    conn.commit()
    browser = FakeBrowser(InspectResult(blocker=None, form_schema=FormSchema(url="https://x/2")))
    service.run_fill(conn, browser, limit=10)
    state, blocker = _state(conn, str(aid))
    assert state == "fill_blocked"
    assert blocker == "broken_flow"
    assert browser.filled is None


def test_redirect_to_other_post_blocks_and_signals_dedup(db_schema, tmp_path):
    conn, _ = db_schema
    _apply(conn)
    aid = _seed(conn, tmp_path)
    schema = FormSchema(url="https://job-boards.greenhouse.io/acme/jobs/2", fields=[])
    browser = FakeBrowser(InspectResult(blocker=None, form_schema=schema))
    summary = service.run_fill(conn, browser, limit=10)
    assert summary.blocked == 1
    assert _state(conn, aid) == ("fill_blocked", "destination_redirect")
    assert browser.filled is None  # чужую форму не заполняли
    with conn.cursor() as cur:
        cur.execute("select count(*) from event where event_type='vacancy.requisition_duplicate'")
        assert cur.fetchone()[0] == 1


def test_same_post_other_url_rebinds_package(db_schema, tmp_path):
    from job_machine.fill.store import load_manifest
    conn, _ = db_schema
    _apply(conn)
    aid = _seed(conn, tmp_path)
    final = "https://job-boards.greenhouse.io/acme/jobs/1"  # тот же пост, другой хост
    schema = FormSchema(url=final, file_inputs=["job_application[resume]"], fields=[
        FormField(name="job_application[first_name]", field_type="text", required=True),
        FormField(name="job_application[last_name]", field_type="text", required=True),
        FormField(name="job_application[email]", field_type="email", required=True),
        FormField(name="job_application[resume]", field_type="file", required=True),
    ])
    browser = FakeBrowser(InspectResult(blocker=None, form_schema=schema))
    summary = service.run_fill(conn, browser, limit=10)
    assert summary.pre_submit_ready == 1
    rebound_path = tmp_path / aid / "manifest.json"
    assert rebound_path.exists()  # legacy-директория уникализирована поддиректорией
    m2 = load_manifest(str(rebound_path))
    assert m2.destination_url == final
    with conn.cursor() as cur:
        cur.execute("select payload_hash, final_apply_url from application "
                    "where application_id=%s", (str(aid),))
        ph, fau = cur.fetchone()
        assert fau == final
        assert ph == m2.payload_hash  # БД и manifest согласованы
        cur.execute("select count(*) from artifact where application_id=%s "
                    "and artifact_type='approval_summary'", (str(aid),))
        assert cur.fetchone()[0] == 2  # старая + перегенерированная сводка
        cur.execute("select count(*) from event where entity_id=%s "
                    "and event_type='application.destination_resolved'", (str(aid),))
        assert cur.fetchone()[0] == 1
    # сводка перегенерирована с финальным URL
    summary_md = (tmp_path / aid / "disclosed-summary.ru.md").read_text(encoding="utf-8")
    assert final in summary_md


def test_equal_url_records_final_apply_url_without_rebind(db_schema, tmp_path):
    conn, _ = db_schema
    _apply(conn)
    aid = _seed(conn, tmp_path)
    dest = MANIFEST["destination_url"]
    schema = FormSchema(url=dest, file_inputs=["job_application[resume]"], fields=[
        FormField(name="job_application[first_name]", field_type="text", required=True),
        FormField(name="job_application[last_name]", field_type="text", required=True),
        FormField(name="job_application[email]", field_type="email", required=True),
        FormField(name="job_application[resume]", field_type="file", required=True),
    ])
    browser = FakeBrowser(InspectResult(blocker=None, form_schema=schema))
    service.run_fill(conn, browser, limit=10)
    with conn.cursor() as cur:
        cur.execute("select final_apply_url from application where application_id=%s",
                    (str(aid),))
        assert cur.fetchone()[0] == dest
        cur.execute("select count(*) from event where entity_id=%s "
                    "and event_type='application.destination_resolved'", (str(aid),))
        assert cur.fetchone()[0] == 0  # без ребинда


def test_resume_after_handoff_not_found(db_schema):
    conn, _ = db_schema
    _apply(conn)
    browser = FakeBrowser(InspectResult(blocker=None, form_schema=None))
    result = service.resume_after_handoff(conn, browser, str(uuid.uuid4()), "sid-x")
    assert result == {"ok": False, "error": "not_found"}


def test_resume_after_handoff_success_uses_existing_session_and_releases(db_schema, tmp_path):
    conn, _ = db_schema
    _apply(conn)
    aid = _seed(conn, tmp_path)
    with conn.cursor() as cur:
        cur.execute("update application set state='fill_blocked', "
                    "current_blocker='handoff_manual' "
                    "where application_id=%s", (aid,))
    conn.commit()
    schema = FormSchema(url=MANIFEST["destination_url"],
                        file_inputs=["job_application[resume]"], fields=[
        FormField(name="job_application[first_name]", field_type="text", required=True),
        FormField(name="job_application[last_name]", field_type="text", required=True),
        FormField(name="job_application[email]", field_type="email", required=True),
        FormField(name="job_application[resume]", field_type="file", required=True),
    ])
    browser = FakeBrowser(InspectResult(blocker=None, form_schema=schema))
    result = service.resume_after_handoff(conn, browser, aid, "handoff-sid")
    assert result == {"ok": True, "status": "pre_submit_ready"}
    assert _state(conn, aid) == ("pre_submit_ready", None)
    assert browser.filled["job_application[email]"] == "a@b.com"
    assert browser.released == "handoff-sid"
    assert browser.disposed is False   # НЕ create_session/dispose — существующая сессия


def test_resume_after_handoff_still_blocked_keeps_session(db_schema, tmp_path):
    """Капча всё ещё не пройдена — сессия НЕ освобождается, попытку можно повторить."""
    conn, _ = db_schema
    _apply(conn)
    aid = _seed(conn, tmp_path)
    browser = FakeBrowser(InspectResult(blocker="captcha", form_schema=None))
    result = service.resume_after_handoff(conn, browser, aid, "handoff-sid")
    assert result == {"ok": False, "error": "still_blocked", "blocker": "captcha"}
    assert browser.released is None
    assert _state(conn, aid) == ("fill_blocked", "captcha")


def test_resume_after_handoff_login_wall_still_blocked_keeps_session(db_schema, tmp_path):
    """login_wall — тот же паттерн, что captcha/mfa/anti_bot: владелец логинится вручную
    через noVNC, сессию нельзя освобождать до повторной попытки (review 07.07)."""
    conn, _ = db_schema
    _apply(conn)
    aid = _seed(conn, tmp_path)
    browser = FakeBrowser(InspectResult(blocker="login_wall", form_schema=None))
    result = service.resume_after_handoff(conn, browser, aid, "handoff-sid")
    assert result == {"ok": False, "error": "still_blocked", "blocker": "login_wall"}
    assert browser.released is None
    assert _state(conn, aid) == ("fill_blocked", "login_wall")


def test_resume_after_handoff_unmatched_required_hands_off_to_agent(db_schema, tmp_path):
    """Несопоставленное required-поле после снятия капчи — уже НЕ терминальный блокер
    (спека 2026-08-06): страница передаётся агенту, сессия НЕ освобождается (retain
    внутри _process_fill уже защитил её от dispose)."""
    conn, _ = db_schema
    _apply(conn)
    aid = _seed(conn, tmp_path)
    schema = FormSchema(url=MANIFEST["destination_url"], fields=[
        FormField(name="job_application[answers_attributes][0][text_value]", field_type="text",
                  label="Are you authorized to work in the EU?", required=True),
    ])
    browser = FakeBrowser(InspectResult(blocker=None, form_schema=schema))
    result = service.resume_after_handoff(conn, browser, aid, "handoff-sid")
    assert result == {"ok": True, "status": "agent_fill_pending"}
    assert browser.retained == ["handoff-sid"]
    assert browser.force_released == []
    assert _state(conn, aid) == ("agent_fill_pending", None)


def test_resume_after_handoff_session_expired(db_schema, tmp_path):
    """Сессия потеряна (воркер перезапущен) — inspect_current 404 → session_expired,
    без падения исключением наружу."""
    conn, _ = db_schema
    _apply(conn)
    aid = _seed(conn, tmp_path)

    class ExpiredBrowser(FakeBrowser):
        def inspect_current(self, sid):
            req = httpx.Request("POST", "http://x/inspect")
            resp = httpx.Response(404, request=req)
            raise httpx.HTTPStatusError("404", request=req, response=resp)

    browser = ExpiredBrowser(InspectResult(blocker=None, form_schema=None))
    result = service.resume_after_handoff(conn, browser, aid, "dead-sid")
    assert result == {"ok": False, "error": "session_expired"}


def _seed_agent_fill(conn, tmp_path, *, state, minutes_ago, session_id="sess-1"):
    """Как _seed, но заявка уже держит агентскую сессию: state произвольный (agent_fill_pending
    ИЛИ уведённый refile_application 'failed' — свип смотрит на session_id, не на state),
    agent_fill_started_at сдвинут на minutes_ago назад."""
    aid = _seed(conn, tmp_path)
    with conn.cursor() as cur:
        cur.execute(
            "update application set state=%s, agent_fill_session_id=%s, "
            "agent_fill_started_at = now() - make_interval(mins => %s) "
            "where application_id=%s",
            (state, session_id, minutes_ago, aid))
    conn.commit()
    return aid


@pytest.mark.parametrize('operation', ['done', 'blocked'])
def test_agent_result_cas_rejects_old_session_and_state(db_schema, tmp_path, operation):
    from job_machine.mcp import agent_fill_store
    conn, _ = db_schema
    _apply(conn)
    aid = _seed_agent_fill(conn, tmp_path, state='agent_fill_pending', minutes_ago=1)
    def record(sid):
        if operation == 'done':
            return agent_fill_store.record_agent_fill_done(conn, aid, sid)
        return agent_fill_store.record_agent_fill_blocked(conn, aid, 'timeout', sid)
    assert record('old-session') is False
    assert _state(conn, aid)[0] == 'agent_fill_pending'
    assert record('sess-1') is True
    assert record('sess-1') is False
    count = conn.execute("select count(*) from event where entity_id=%s and event_type=%s",
                         (aid, 'application.agent_fill_' + operation)).fetchone()[0]
    assert count == 1


def test_sweep_leaves_submitting_session_alive(db_schema, tmp_path):
    conn, _ = db_schema
    _apply(conn)
    aid = _seed_agent_fill(conn, tmp_path, state='submitting', minutes_ago=30)
    browser = FakeBrowser(InspectResult(blocker=None, form_schema=None))
    assert service.sweep_agent_fill_timeouts(conn, browser, 15) == 0
    assert browser.force_released == []
    assert _state(conn, aid)[0] == 'submitting'


def test_sweep_rechecks_session_after_snapshot(db_schema, tmp_path, monkeypatch):
    conn, _ = db_schema
    _apply(conn)
    aid = _seed_agent_fill(conn, tmp_path, state='agent_fill_pending', minutes_ago=30)
    snapshot = service.store.pull_stale_agent_fills(conn, 15)
    conn.execute("update application set agent_fill_session_id='replacement' where application_id=%s", (aid,))
    conn.commit()
    monkeypatch.setattr(service.store, 'pull_stale_agent_fills', lambda *a: snapshot)
    browser = FakeBrowser(InspectResult(blocker=None, form_schema=None))
    assert service.sweep_agent_fill_timeouts(conn, browser, 15) == 0
    assert browser.force_released == []
    assert conn.execute("select agent_fill_session_id from application where application_id=%s", (aid,)).fetchone()[0] == 'replacement'


def test_failed_release_keeps_cleanup_retryable(db_schema, tmp_path):
    conn, _ = db_schema
    _apply(conn)
    aid = _seed_agent_fill(conn, tmp_path, state='agent_fill_pending', minutes_ago=30)
    class UnreachableBrowser:
        def release(self, sid):
            raise httpx.ConnectError('synthetic outage')
    assert service.sweep_agent_fill_timeouts(conn, UnreachableBrowser(), 15) == 0
    assert _state(conn, aid)[0] == 'agent_fill_pending'
    assert conn.execute("select agent_fill_session_id from application where application_id=%s", (aid,)).fetchone()[0] == 'sess-1'


def test_missing_browser_session_is_reconciled(db_schema, tmp_path):
    conn, _ = db_schema
    _apply(conn)
    aid = _seed_agent_fill(conn, tmp_path, state='agent_fill_pending', minutes_ago=30)
    class RestartedBrowser:
        def release(self, sid):
            response = httpx.Response(404, request=httpx.Request('POST','http://synthetic/release'))
            response.raise_for_status()
    assert service.sweep_agent_fill_timeouts(conn, RestartedBrowser(), 15) == 1
    assert _state(conn, aid)[0] == 'fill_blocked'


def test_pending_cannot_replace_another_session(db_schema, tmp_path):
    conn, _ = db_schema
    _apply(conn)
    aid = _seed_agent_fill(conn, tmp_path, state='agent_fill_pending', minutes_ago=1)
    assert service.store.record_agent_fill_pending(conn, aid, 'replacement', 'http://synthetic', []) is False
    assert conn.execute("select agent_fill_session_id from application where application_id=%s", (aid,)).fetchone()[0] == 'sess-1'


def test_agent_context_reads_real_bound_package(db_schema, tmp_path):
    import hashlib
    from job_machine.package.builder import build_package
    from job_machine.package.models import PackageInput, ResumeArtifact, AnswerRecord
    conn, _ = db_schema
    _apply(conn)
    aid = _seed_agent_fill(conn, tmp_path, state='agent_fill_pending', minutes_ago=1)
    manifest = build_package(PackageInput(application_id=str(aid), company='Synthetic', role='Tester',
        destination_url='https://example.com/apply'),
        [AnswerRecord(field='phone',value='555',state='locked')],
        ResumeArtifact(filename='r.pdf',path='r.pdf',content_hash='synthetic'))
    data = manifest.model_dump_json().encode()
    (tmp_path/'manifest.json').write_bytes(data)
    conn.execute("update artifact set content_hash=%s where application_id=%s and artifact_type='manifest'",
                 (hashlib.sha256(data).hexdigest(), aid))
    conn.execute("update application set payload_hash=%s where application_id=%s", (manifest.payload_hash, aid))
    result = service.agent_fill_context(conn, str(aid), 'sess-1')
    assert result['answers'] == [{'field':'phone','value':'555','source':'locked'}]
    conn.execute("update application set payload_hash='changed' where application_id=%s", (aid,))
    assert service.agent_fill_context(conn, str(aid), 'sess-1')['error'] == 'package_unverified'


def test_repeated_resume_does_not_release_winning_session(db_schema, tmp_path):
    conn, _ = db_schema
    _apply(conn)
    aid = _seed_agent_fill(conn, tmp_path, state='agent_fill_pending', minutes_ago=1)
    schema = FormSchema(url=MANIFEST['destination_url'], fields=[
        FormField(name='unknown',field_type='text',label='Unknown required',required=True)])
    browser = FakeBrowser(InspectResult(form_schema=schema))
    result = service.resume_after_handoff(conn,browser,aid,'sess-1')
    assert result['error'] == 'stale_fill'
    assert browser.force_released == []
    assert _state(conn,aid)[0] == 'agent_fill_pending'
    assert browser.filled is None


@pytest.mark.parametrize('state', ['needs_package','package_ready'])
def test_sweep_reclaims_reopened_session_without_changing_state(db_schema,tmp_path,state):
    conn, _ = db_schema
    _apply(conn)
    aid = _seed_agent_fill(conn,tmp_path,state=state,minutes_ago=30)
    browser = FakeBrowser(InspectResult())
    assert service.sweep_agent_fill_timeouts(conn,browser,15) == 1
    assert _state(conn,aid)[0] == state
    assert conn.execute('select agent_fill_session_id from application where application_id=%s',(aid,)).fetchone()[0] is None


def test_stale_agent_session_is_reclaimed(db_schema, tmp_path):
    """Агент не добил заявку за отведённое время → воркер сам освобождает
    страницу и ставит блокер. Контексты Chromium не копятся."""
    conn, _ = db_schema
    _apply(conn)
    aid = _seed_agent_fill(conn, tmp_path, state="agent_fill_pending", minutes_ago=30)
    browser = FakeBrowser(InspectResult(blocker=None, form_schema=None))

    reclaimed = service.sweep_agent_fill_timeouts(conn, browser, timeout_minutes=15)

    assert reclaimed == 1
    assert browser.force_released == ["sess-1"]
    assert _state(conn, aid) == ("fill_blocked", "agent_fill_timeout")
    with conn.cursor() as cur:
        cur.execute("select agent_fill_session_id, agent_fill_started_at from application "
                    "where application_id=%s", (str(aid),))
        assert cur.fetchone() == (None, None)


def test_sweep_reclaims_session_after_refile(db_schema, tmp_path):
    """refile увёл заявку из agent_fill_pending в failed, но страница осталась
    retained: обычный dispose её не закроет, sweep_orphaned_contexts не увидит.
    Свип обязан освободить её по session_id, не переписывая исход заявки."""
    conn, _ = db_schema
    _apply(conn)
    aid = _seed_agent_fill(conn, tmp_path, state="failed", minutes_ago=30)
    browser = FakeBrowser(InspectResult(blocker=None, form_schema=None))

    reclaimed = service.sweep_agent_fill_timeouts(conn, browser, timeout_minutes=15)

    assert reclaimed == 1
    assert browser.force_released == ["sess-1"]
    assert _state(conn, aid)[0] == "failed"      # исход НЕ переписан
    with conn.cursor() as cur:
        cur.execute("select agent_fill_session_id from application where application_id=%s",
                    (str(aid),))
        assert cur.fetchone()[0] is None


def test_fresh_agent_session_not_swept(db_schema, tmp_path):
    """Свежая (не протухшая) агентская сессия свипом НЕ трогается."""
    conn, _ = db_schema
    _apply(conn)
    aid = _seed_agent_fill(conn, tmp_path, state="agent_fill_pending", minutes_ago=1)
    browser = FakeBrowser(InspectResult(blocker=None, form_schema=None))

    reclaimed = service.sweep_agent_fill_timeouts(conn, browser, timeout_minutes=15)

    assert reclaimed == 0
    assert browser.force_released == []
    assert _state(conn, aid) == ("agent_fill_pending", None)
    with conn.cursor() as cur:
        cur.execute("select agent_fill_session_id from application where application_id=%s",
                    (str(aid),))
        assert cur.fetchone()[0] == "sess-1"


def test_resume_after_handoff_unexpected_exception_releases_session_and_records_broken_flow(db_schema, tmp_path):
    """Непредвиденное исключение (не httpx.HTTPStatusError) внутри _process_fill —
    не должно утекать наружу необработанным: сессия освобождается, заявка получает
    диагностируемый broken_flow, ошибка не пробрасывается вызывающему."""
    conn, _ = db_schema
    _apply(conn)
    aid = _seed(conn, tmp_path)

    class ExplodingBrowser(FakeBrowser):
        def inspect_current(self, sid):
            raise ValueError("неожиданная ошибка, не связанная с HTTP-статусом сессии")

    browser = ExplodingBrowser(InspectResult(blocker=None, form_schema=None))
    result = service.resume_after_handoff(conn, browser, aid, "handoff-sid")
    assert result == {"ok": False, "error": "broken_flow"}
    assert browser.released == "handoff-sid"
    assert _state(conn, aid) == ("fill_blocked", "broken_flow")
