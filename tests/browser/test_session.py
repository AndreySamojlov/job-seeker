import pytest

pytest.importorskip("playwright")

pytestmark = pytest.mark.browser


async def test_create_then_dispose(browser_manager):
    sid = await browser_manager.create_session()
    assert browser_manager.info(sid)["status"] == "open"
    await browser_manager.dispose_session(sid)
    assert browser_manager.info(sid) is None


async def test_dispose_is_idempotent(browser_manager):
    await browser_manager.dispose_session("nope")  # no error


async def test_sessions_are_isolated(browser_manager):
    a = await browser_manager.create_session()
    b = await browser_manager.create_session()
    ctx_a = browser_manager.get_page(a).context
    await ctx_a.add_cookies(
        [{"name": "k", "value": "a", "url": "https://example.com"}]
    )
    ctx_b = browser_manager.get_page(b).context
    assert await ctx_b.cookies("https://example.com") == []


async def test_artifact_path_under_dir(browser_manager, tmp_path):
    sid = await browser_manager.create_session()
    path = browser_manager.artifact_path(sid, "inspect.png")
    assert path.endswith("inspect.png")
    assert str(tmp_path) in path


async def test_render_pdf_reuses_work_browser_no_extra_launch(browser_manager):
    """render_pdf не должен поднимать отдельный Chromium на каждый вызов —
    иначе конкурентные /pdf-запросы плодят полные браузерные процессы поверх
    уже работающего work-браузера (см. lab-do OOM: 5 PDF-рендеров подряд
    подняли PID со 117MiB до 512MiB за 5 минут)."""
    launch_calls = []
    orig_launch = browser_manager._pw.chromium.launch

    async def counting_launch(*args, **kwargs):
        launch_calls.append((args, kwargs))
        return await orig_launch(*args, **kwargs)

    browser_manager._pw.chromium.launch = counting_launch

    pdf = await browser_manager.render_pdf("<html><body><h1>CV</h1></body></html>")
    assert pdf.startswith(b"%PDF")
    assert launch_calls == [], "render_pdf запустил отдельный Chromium вместо переиспользования work-браузера"

    pdf2 = await browser_manager.render_pdf("<html><body><h1>CV2</h1></body></html>")
    assert pdf2.startswith(b"%PDF")
    assert launch_calls == []


async def test_render_pdf_closes_its_page(browser_manager):
    """render_pdf не должен оставлять открытые страницы в work-браузере."""
    before = len(browser_manager._work_browser.contexts)
    await browser_manager.render_pdf("<html><body>x</body></html>")
    after = len(browser_manager._work_browser.contexts)
    assert after == before


async def test_dispose_session_bounded_by_timeout_on_hanging_close(browser_manager):
    """Если context.close() зависает (недоступный/деградировавший браузер),
    dispose_session не должен висеть вечно — таймаут ограничивает ожидание."""
    import asyncio

    sid = await browser_manager.create_session()
    sess = browser_manager._sessions[sid]
    real_context = sess["context"]

    async def hanging_close():
        await asyncio.sleep(999)

    real_context.close = hanging_close
    browser_manager._close_timeout = 0.2

    await asyncio.wait_for(browser_manager.dispose_session(sid), timeout=2.0)
    assert browser_manager.info(sid) is None


async def test_sweep_orphaned_contexts_closes_lost_context(browser_manager):
    """Контекст, потерянный из _sessions (например, после сбойного dispose),
    должен закрываться watchdog-свипом, а не течь до конца жизни контейнера."""
    sid = await browser_manager.create_session()
    context = browser_manager.get_page(sid).context
    # Симулируем сбойный dispose: bookkeeping потерян, но контекст не закрыт.
    del browser_manager._sessions[sid]
    assert context in browser_manager._work_browser.contexts

    closed = await browser_manager.sweep_orphaned_contexts()

    assert closed == 1
    assert context not in browser_manager._work_browser.contexts


async def test_sweep_orphaned_contexts_leaves_tracked_sessions_alone(browser_manager):
    sid = await browser_manager.create_session()
    closed = await browser_manager.sweep_orphaned_contexts()
    assert closed == 0
    assert browser_manager.info(sid) is not None


async def test_ensure_work_browser_alive_concurrent_calls_launch_once(browser_manager):
    """Конкурентные вызовы после падения work-браузера не должны каждый поднимать
    свой Chromium: проигравший гонку экземпляр никогда не попадёт в _work_browser,
    останется неотслеживаемым (sweep смотрит только на текущий self._work_browser)
    и утечёт — тот же баг, который эта серия правок чинит, но в момент восстановления."""
    import asyncio

    await browser_manager._work_browser.close()

    launch_calls = []
    orig_launch = browser_manager._pw.chromium.launch

    async def slow_launch(*args, **kwargs):
        launch_calls.append(1)
        await asyncio.sleep(0.2)
        return await orig_launch(*args, **kwargs)

    browser_manager._pw.chromium.launch = slow_launch

    await asyncio.gather(
        browser_manager._ensure_work_browser_alive(),
        browser_manager._ensure_work_browser_alive(),
    )

    assert len(launch_calls) == 1
    assert browser_manager._work_browser.is_connected()


async def test_ensure_work_browser_alive_evicts_stale_sessions_keeps_persist(browser_manager):
    """После перезапуска мёртвого work-браузера сессии на нём вычищаются из
    реестра (страницы всё равно нерабочие); persist/handoff-сессии на другом
    браузере не трогаются."""
    sid = await browser_manager.create_session()
    persist_sid = await browser_manager.create_session(persist=True)

    await browser_manager._work_browser.close()
    await browser_manager._ensure_work_browser_alive()

    assert browser_manager.info(sid) is None
    assert browser_manager.info(persist_sid) is not None
