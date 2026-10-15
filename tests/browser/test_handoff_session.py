"""Тесты persist-сессий (handoff) в SessionManager."""
import pytest

pytest.importorskip("playwright")

pytestmark = pytest.mark.browser


async def test_persist_session_survives_normal_dispose(browser_manager):
    """Persist-сессия не убивается обычным dispose_session."""
    sid = await browser_manager.create_session(persist=True)
    info = browser_manager.info(sid)
    assert info is not None
    assert info["status"] == "handoff"

    # обычный dispose — НЕ убивает persist-сессию
    await browser_manager.dispose_session(sid)
    assert browser_manager.info(sid) is not None, "persist-сессия должна выжить"
    assert browser_manager.info(sid)["status"] == "handoff"


async def test_persist_session_killed_by_force(browser_manager):
    """force=True убивает persist-сессию."""
    sid = await browser_manager.create_session(persist=True)
    assert browser_manager.info(sid)["status"] == "handoff"

    await browser_manager.dispose_session(sid, force=True)
    assert browser_manager.info(sid) is None


async def test_normal_session_status_open(browser_manager):
    """Обычная сессия имеет статус 'open'."""
    sid = await browser_manager.create_session()
    assert browser_manager.info(sid)["status"] == "open"


async def test_normal_session_killed_by_regular_dispose(browser_manager):
    """Обычная сессия убивается обычным dispose."""
    sid = await browser_manager.create_session(persist=False)
    await browser_manager.dispose_session(sid)
    assert browser_manager.info(sid) is None


async def test_shutdown_kills_persist_sessions(browser_manager, tmp_path):
    """shutdown форсит уничтожение всех сессий включая persist."""
    from job_machine.browser.session import SessionManager
    mgr = SessionManager(headless=True, artifact_dir=tmp_path)
    await mgr.start()

    sid = await mgr.create_session(persist=True)
    assert mgr.info(sid) is not None

    await mgr.shutdown()
    # После shutdown сессии нет (реестр пуст)
    assert mgr.info(sid) is None


async def test_retain_protects_work_session_from_dispose(tmp_path):
    """retain делает обычную (headless, work-браузер) сессию защищённой от dispose:
    страница переживает выход из _fill_one и ждёт агента. Headful-браузер при этом
    НЕ поднимается — лишний headful Chromium уронил хост 2026-07-06."""
    from job_machine.browser.session import SessionManager
    mgr = SessionManager(headless=True, artifact_dir=tmp_path)
    await mgr.start()
    try:
        sid = await mgr.create_session()

        assert mgr.retain(sid) is True
        await mgr.dispose_session(sid)
        assert mgr.info(sid) is not None
        assert mgr.handoff_active is False
        assert mgr.handoff_refcount == 0

        await mgr.dispose_session(sid, force=True)
        assert mgr.info(sid) is None
        assert mgr.handoff_refcount == 0
    finally:
        await mgr.shutdown()


async def test_agent_cycle_leaves_no_contexts():
    """Полный цикл агент-пути (создать → retain → force-release) возвращает число
    живых контекстов к исходному. Утечка контекстов — путь к OOM хоста."""
    from job_machine.browser.session import SessionManager

    mgr = SessionManager(headless=True)
    await mgr.start()
    try:
        before = len(mgr._work_browser.contexts)

        sid = await mgr.create_session()
        mgr.retain(sid)
        await mgr.dispose_session(sid)          # обычный dispose — no-op
        assert len(mgr._work_browser.contexts) == before + 1
        await mgr.dispose_session(sid, force=True)

        assert len(mgr._work_browser.contexts) == before
        assert await mgr.sweep_orphaned_contexts() == 0
    finally:
        await mgr.shutdown()


async def test_retain_unknown_session_returns_false(tmp_path):
    from job_machine.browser.session import SessionManager
    mgr = SessionManager(headless=True, artifact_dir=tmp_path)
    await mgr.start()
    try:
        assert mgr.retain("nope") is False
    finally:
        await mgr.shutdown()


async def test_retain_reports_status_retained_not_handoff(tmp_path):
    """Ретейненная work-сессия — не handoff: у неё нет headful-браузера и она
    НЕ должна читаться агентом как «идёт ручной noVNC-takeover»."""
    from job_machine.browser.session import SessionManager
    mgr = SessionManager(headless=True, artifact_dir=tmp_path)
    await mgr.start()
    try:
        sid = await mgr.create_session()
        mgr.retain(sid)
        assert mgr.info(sid)["status"] == "retained"
    finally:
        await mgr.shutdown()


class _FakeChromium:
    def __init__(self, captured):
        self._captured = captured

    async def launch(self, **kwargs):
        self._captured.update(kwargs)
        return object()


class _FakePw:
    def __init__(self, captured):
        self.chromium = _FakeChromium(captured)


async def _work_browser_launch_args():
    from job_machine.browser.session import SessionManager

    captured = {}
    mgr = SessionManager(headless=True)
    mgr._pw = _FakePw(captured)
    await mgr._ensure_work_browser_alive()
    return captured.get("args") or []


async def test_work_browser_exposes_cdp_port_when_enabled(monkeypatch):
    """Агент присоединяется к УЖЕ запущенному Chromium по CDP и никогда не лончит
    свой — второй Chromium на контейнер уронил хост 2026-07-06."""
    monkeypatch.setenv("BROWSER_CDP_PORT", "9222")

    args = await _work_browser_launch_args()

    assert "--remote-debugging-port=9222" in args
    assert "--remote-debugging-address=0.0.0.0" in args


async def test_work_browser_has_no_cdp_port_by_default(monkeypatch):
    """Без явного BROWSER_CDP_PORT порт не открывается. CDP это полный контроль над
    браузером, которым подаются заявки, — включать его должен деплой, а не импорт
    модуля. Плюс порт фиксированный: с ним второй Chromium на той же машине уже не
    поднимается (bind() returned an error), а рядом с work-браузером лениво встаёт
    headful handoff-браузер."""
    monkeypatch.delenv("BROWSER_CDP_PORT", raising=False)

    args = await _work_browser_launch_args()

    assert args == []


async def test_retain_twice_is_idempotent(tmp_path):
    """Повторный retain() на уже retained сессии не двигает handoff_refcount и
    не поднимает headful-браузер; сессия по-прежнему переживает обычный dispose."""
    from job_machine.browser.session import SessionManager
    mgr = SessionManager(headless=True, artifact_dir=tmp_path)
    await mgr.start()
    try:
        sid = await mgr.create_session()

        assert mgr.retain(sid) is True
        assert mgr.retain(sid) is True
        assert mgr.handoff_refcount == 0
        assert mgr.handoff_active is False

        await mgr.dispose_session(sid)
        assert mgr.info(sid) is not None
        assert mgr.handoff_refcount == 0
    finally:
        await mgr.shutdown()
