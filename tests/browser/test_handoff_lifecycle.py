"""Тесты lazy-lifecycle handoff-браузера: refcount, переиспользование, teardown."""
import asyncio

import pytest

pytest.importorskip("playwright")

pytestmark = pytest.mark.browser


async def test_no_handoff_browser_until_first_handoff(browser_manager):
    assert browser_manager.handoff_active is False
    await browser_manager.create_session(persist=False)
    assert browser_manager.handoff_active is False


async def test_first_handoff_lazily_starts_handoff_browser(browser_manager):
    await browser_manager.create_session(persist=True)
    assert browser_manager.handoff_active is True
    assert browser_manager.handoff_refcount == 1


async def test_second_concurrent_handoff_reuses_same_browser(browser_manager):
    await browser_manager.create_session(persist=True)
    browser_after_first = browser_manager._handoff_browser
    await browser_manager.create_session(persist=True)
    assert browser_manager._handoff_browser is browser_after_first
    assert browser_manager.handoff_refcount == 2


async def test_release_last_handoff_tears_down_browser(browser_manager):
    sid = await browser_manager.create_session(persist=True)
    await browser_manager.dispose_session(sid, force=True)
    assert browser_manager.handoff_active is False
    assert browser_manager.handoff_refcount == 0


async def test_release_one_of_two_keeps_browser_alive(browser_manager):
    sid1 = await browser_manager.create_session(persist=True)
    await browser_manager.create_session(persist=True)
    await browser_manager.dispose_session(sid1, force=True)
    assert browser_manager.handoff_active is True
    assert browser_manager.handoff_refcount == 1


async def test_shutdown_tears_down_handoff_browser_too(tmp_path):
    from job_machine.browser.session import SessionManager
    mgr = SessionManager(headless=True, artifact_dir=tmp_path)
    await mgr.start()
    await mgr.create_session(persist=True)
    await mgr.shutdown()
    assert mgr.handoff_active is False


async def test_concurrent_create_and_dispose_no_race(browser_manager):
    """Гонка между конкурентными create/dispose не должна ронять refcount/browser."""
    async def create_and_dispose():
        sid = await browser_manager.create_session(persist=True)
        await asyncio.sleep(0.01)
        await browser_manager.dispose_session(sid, force=True)

    await asyncio.gather(
        create_and_dispose(),
        create_and_dispose(),
    )
    assert browser_manager.handoff_refcount == 0
    assert browser_manager.handoff_active is False
