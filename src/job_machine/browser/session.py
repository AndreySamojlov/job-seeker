"""Изолированные браузерные сессии поверх Playwright (async API).

Два независимых браузера: `_work_browser` (headless, всегда поднят — обслуживает
обычные fill/inspect/submit/pdf сессии) и `_handoff_browser` (headful под Xvfb+VNC,
лениво поднимается только на реальный /handoff и гасится после последнего release —
устраняет конкуренцию за рендер между автоматизацией и ручным CAPTCHA/MFA-takeover,
см. docs/superpowers/specs/2026-07-06-browser-worker-headless-handoff-split-design.md).

В тестах (headless=True) handoff-браузер тоже headless и Xvfb/VNC не поднимаются —
никакой реальный дисплей для CI не нужен.
"""

import asyncio
import contextlib
import logging
import os
import uuid
from pathlib import Path

from playwright.async_api import async_playwright

from job_machine.browser.display import DisplayManager

log = logging.getLogger(__name__)


def _work_browser_args():
    """Аргументы запуска work-браузера: CDP-эндпоинт, если он явно включён.

    К этому эндпоинту присоединяется агент (готовый Playwright MCP в режиме
    --cdp-endpoint), чтобы дозаполнить форму на той же живой странице.

    Выключен по умолчанию и включается только переменной BROWSER_CDP_PORT. Причин
    две. Первая: CDP — полный контроль над браузером, которым подаются заявки, и
    открывать его по умолчанию везде, где импортируется этот модуль, неправильно;
    ширину доступа выбирает деплой (решение владельца 2026-08-07 — слушаем 0.0.0.0
    ВНУТРИ контейнера, иначе docker не опубликует порт, а наружу публикуем только
    на 127.0.0.1 хоста, доступ ssh-туннелем). Вторая: порт фиксированный, а второй
    Chromium на ту же машину с ним уже не поднимется — `bind() returned an error`
    и таймаут запуска. В проде рядом с work-браузером лениво поднимается headful
    handoff-браузер, в тестах — по SessionManager на тест; обоим CDP не нужен.

    --remote-allow-origins обязателен, хотя по первому впечатлению кажется лишним
    ослаблением. Проверено на живом контейнере 2026-08-07 сырым рукопожатием:
    без заголовка Origin Chromium отдаёт `101 WebSocket Protocol Handshake`,
    с Origin — `403 Forbidden`. Playwright MCP заголовок шлёт, поэтому без флага
    CDP-клиент подключиться не может вообще (ws закрывается кодом 1006). Ослабления
    периметра тут нет: доступ и так ограничен петлёй контейнера, петлёй хоста и
    ssh-туннелем — проверка origin поверх этого ничего не добавляла.
    """
    port = os.environ.get("BROWSER_CDP_PORT")
    if not port:
        return []
    return [
        f"--remote-debugging-port={port}",
        "--remote-debugging-address=0.0.0.0",
        "--remote-allow-origins=*",
    ]


class SessionManager:
    def __init__(self, headless=True, artifact_dir="artifacts/browser",
                 close_timeout=10.0, watchdog_interval=60.0):
        self._handoff_headless = headless
        self._artifact_dir = Path(artifact_dir)
        self._artifact_dir.mkdir(parents=True, exist_ok=True)
        self._pw = None
        self._work_browser = None
        self._handoff_browser = None
        self._handoff_refcount = 0
        self._handoff_lock = asyncio.Lock()
        self._work_browser_lock = asyncio.Lock()
        self._display = DisplayManager()
        self._sessions = {}
        self._close_timeout = close_timeout
        self._watchdog_interval = watchdog_interval
        self._watchdog_task = None

    @property
    def handoff_active(self) -> bool:
        """True, если headful handoff-браузер сейчас поднят."""
        return self._handoff_browser is not None

    @property
    def handoff_refcount(self) -> int:
        """Число живых headful-сессий (на handoff-браузере), а не всех persist-сессий:
        retain() защищает work-сессию от dispose без headful, refcount её не считает."""
        return self._handoff_refcount

    async def start(self):
        """Запустить Playwright, headless work-браузер и watchdog (вызывать в lifespan воркера)."""
        self._pw = await async_playwright().start()
        self._work_browser = await self._pw.chromium.launch(
            headless=True, args=_work_browser_args())
        self._watchdog_task = asyncio.create_task(self._watchdog_loop())

    async def _bounded_close(self, closeable, what: str):
        """Закрыть context/page/browser с таймаутом; при сбое — лог, без исключения наверх.

        Зависший/недоступный Chromium не должен блокировать вызывающего (dispose,
        render_pdf, watchdog) навечно — таймаут гарантирует прогресс. Если сама
        попытка close() не сработала, объект остаётся жить в браузере как orphan —
        его подберёт следующий sweep_orphaned_contexts (defense in depth).
        """
        try:
            await asyncio.wait_for(closeable.close(), timeout=self._close_timeout)
        except Exception:
            log.warning("не удалось закрыть %s за %.1fs", what, self._close_timeout, exc_info=True)

    async def _ensure_work_browser_alive(self):
        """Перезапустить work-браузер, если он отвалился (например, OOM-kill).

        Самовосстановление без внешнего docker restart. Сессии, привязанные к
        мёртвому браузеру, всё равно нерабочие — вычищаем их из реестра.

        Под _work_browser_lock: без него два конкурентных вызова после падения
        браузера оба видят is_connected()==False и оба лончат Chromium — тот, что
        не победил присваивание self._work_browser, никогда не отслеживается и
        не попадёт под sweep_orphaned_contexts (он смотрит только на текущий
        self._work_browser) — leak в момент восстановления, тот же класс бага,
        который этот метод должен чинить.
        """
        async with self._work_browser_lock:
            if self._work_browser is not None and self._work_browser.is_connected():
                return
            if self._work_browser is not None:
                log.warning("work-браузер отключился — перезапуск")
            dead = self._work_browser
            self._work_browser = await self._pw.chromium.launch(
                headless=True, args=_work_browser_args())
            stale = [sid for sid, sess in self._sessions.items()
                     if sess["context"].browser is dead]
            for sid in stale:
                self._sessions.pop(sid, None)

    async def _ensure_handoff_browser(self):
        """Лениво поднять headful-браузер (+ Xvfb/VNC). Вызывать под _handoff_lock."""
        if self._handoff_browser is not None:
            return
        if not self._handoff_headless:
            self._display.start()
        self._handoff_browser = await self._pw.chromium.launch(headless=self._handoff_headless)

    async def _teardown_handoff_browser(self):
        """Погасить headful-браузер (+ Xvfb/VNC). Вызывать под _handoff_lock при refcount == 0."""
        if self._handoff_browser is not None:
            await self._bounded_close(self._handoff_browser, "handoff-браузер")
            self._handoff_browser = None
        if not self._handoff_headless:
            self._display.stop()

    async def create_session(self, persist: bool = False):
        """Создать изолированную сессию; вернуть session_id.

        persist=True — «handoff»-сессия на headful-браузере (лениво поднимаемом):
        не уничтожается обычным dispose_session() (только force=True или shutdown).
        Используется при передаче браузера человеку под CAPTCHA/MFA (§3 ТЗ).
        """
        if persist:
            async with self._handoff_lock:
                await self._ensure_handoff_browser()
                self._handoff_refcount += 1
                browser = self._handoff_browser
        else:
            await self._ensure_work_browser_alive()
            browser = self._work_browser
        session_id = uuid.uuid4().hex
        context = await browser.new_context()
        page = await context.new_page()
        # persist — защита от обычного dispose; headful — принадлежность к
        # handoff-браузеру (и, значит, к refcount headful-браузера). Агентская
        # сессия persist, но НЕ headful: она живёт на headless work-браузере.
        self._sessions[session_id] = {"context": context, "page": page,
                                      "persist": persist, "headful": persist}
        return session_id

    async def render_pdf(self, html: str) -> bytes:
        """HTML → PDF на разделяемом headless work-браузере.

        Раньше поднимал отдельный Chromium-процесс на каждый вызов — под нагрузкой
        (несколько /pdf подряд) это плодило полноценные браузерные процессы поверх
        уже работающего work-браузера и было основным источником роста PID/памяти
        job-browser (см. docs по инциденту lab-do OOM).
        """
        await self._ensure_work_browser_alive()
        page = await self._work_browser.new_page()
        try:
            await page.set_content(html, wait_until="load")
            return await page.pdf(format="A4", print_background=True)
        finally:
            await self._bounded_close(page, "PDF-страница")

    async def sweep_orphaned_contexts(self) -> int:
        """Force-close браузерные контексты, потерянные из _sessions (например,
        после сбойного/зависшего dispose). Возвращает число закрытых orphan'ов.

        Вызывается периодически watchdog-циклом — самовосстановление без
        необходимости внешнего docker restart.
        """
        tracked = {sess["context"] for sess in self._sessions.values()}
        orphans = []
        for browser in (self._work_browser, self._handoff_browser):
            if browser is not None and browser.is_connected():
                orphans.extend(c for c in browser.contexts if c not in tracked)
        for ctx in orphans:
            await self._bounded_close(ctx, "orphaned context")
        return len(orphans)

    async def _watchdog_loop(self):
        """Периодически чистит потерянные контексты и поднимает упавший work-браузер."""
        while True:
            try:
                await asyncio.sleep(self._watchdog_interval)
                await self._ensure_work_browser_alive()
                closed = await self.sweep_orphaned_contexts()
                if closed:
                    log.warning("watchdog: закрыто %d потерянных браузерных контекстов", closed)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("watchdog: ошибка при обходе")

    def get_page(self, session_id):
        """Playwright-страница сессии (KeyError если нет)."""
        return self._sessions[session_id]["page"]

    def retain(self, session_id) -> bool:
        """Защитить существующую сессию от обычного dispose (агентский fill).

        Страница должна пережить завершение _fill_one и дождаться агента, оставаясь
        на headless work-браузере. Возвращает False, если сессии нет.
        """
        sess = self._sessions.get(session_id)
        if sess is None:
            return False
        sess["persist"] = True
        return True

    def info(self, session_id):
        """Состояние сессии для API или None, если её нет."""
        sess = self._sessions.get(session_id)
        if sess is None:
            return None
        if sess.get("headful"):
            status = "handoff"
        elif sess.get("persist"):
            status = "retained"
        else:
            status = "open"
        return {
            "session_id": session_id,
            "status": status,
            "current_url": sess["page"].url,
        }

    def artifact_path(self, session_id, suffix):
        """Путь под артефакт сессии (screenshot/trace)."""
        return str(self._artifact_dir / f"{session_id}_{suffix}")

    async def dispose_session(self, session_id, force: bool = False):
        """Закрыть контекст и убрать из реестра (идемпотентно).

        Для persist-сессий (флаг ставится либо при создании через create_session
        (persist=True) — headful handoff-сессия, либо позже через retain() —
        headless work-сессия, ждущая агента): без force=True вызов игнорируется,
        сессия продолжает жить. force=True уничтожает в любом случае; если сессия
        ещё и headful (handoff) и это была последняя такая — гасит headful-браузер.
        Refcount и teardown handoff-браузера смотрят на headful, а не на persist —
        force-release retained work-сессии не должен трогать чужой handoff-браузер.
        """
        sess = self._sessions.get(session_id)
        if sess is None:
            return
        if sess.get("persist") and not force:
            return  # persist-сессия (handoff или retained) защищена
        self._sessions.pop(session_id, None)
        await self._bounded_close(sess["context"], f"контекст сессии {session_id}")
        if sess.get("headful"):
            async with self._handoff_lock:
                self._handoff_refcount = max(0, self._handoff_refcount - 1)
                if self._handoff_refcount == 0:
                    await self._teardown_handoff_browser()

    async def shutdown(self):
        """Закрыть все сессии, оба браузера, watchdog и Playwright (на остановке воркера)."""
        if self._watchdog_task is not None:
            self._watchdog_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._watchdog_task
            self._watchdog_task = None
        for session_id in list(self._sessions):
            await self.dispose_session(session_id, force=True)
        if self._work_browser is not None:
            await self._bounded_close(self._work_browser, "work-браузер")
        self._display.stop()
        if self._pw is not None:
            await self._pw.stop()
