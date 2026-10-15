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
