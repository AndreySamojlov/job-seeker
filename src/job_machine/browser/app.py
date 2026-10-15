"""HTTP-API браузерного воркера (FastAPI).

Маршруты: создание/просмотр/уничтожение изолированной сессии, inspect, fill→stop,
/submit (fill+click+capture — DOM-примитив без гардов, гарды на стороне submit-воркера),
healthz и встроенная тест-форма.
"""

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import FileResponse

from job_machine.browser.blockers import classify_page
from job_machine.browser.fill import fill_form, submit_form
from job_machine.browser.inspect import (
    extract_form_schema,
    extract_signals,
    follow_apply_link_if_present,
    wait_for_fillable_content,
)
from job_machine.browser.novnc import build_novnc_url
from job_machine.browser.schema import (
    ContentRequest,
    ContentResult,
    FillRequest,
    FillResult,
    HandoffRequest,
    HandoffResult,
    InspectRequest,
    InspectResult,
    PdfRequest,
    SessionInfo,
    SubmitRequest,
    SubmitResult,
)
from job_machine.browser.session import SessionManager

FIXTURE = Path(__file__).parent / "fixtures" / "sample_form.html"


def create_app(manager=None):
    """Собрать FastAPI-приложение; manager можно подменить в тестах."""

    @asynccontextmanager
    async def lifespan(app):
        mgr = manager
        if mgr is None:
            # headless=False здесь означает «handoff-браузер headful в проде»;
            # work-браузер для fill/inspect/submit/pdf всегда headless (session.py).
            mgr = SessionManager(
                headless=False,
                artifact_dir=os.environ.get("ARTIFACT_DIR", "artifacts/browser"),
            )
            await mgr.start()
        app.state.manager = mgr
        try:
            yield
        finally:
            if manager is None:
                await mgr.shutdown()

    app = FastAPI(title="job-machine browser worker", lifespan=lifespan)

    def _page_or_404(session_id):
        mgr = app.state.manager
        if mgr.info(session_id) is None:
            raise HTTPException(status_code=404, detail="no such session")
        return mgr.get_page(session_id)

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok"}

    @app.get("/test/sample-form")
    async def sample_form():
        return FileResponse(FIXTURE)

    @app.post("/session", response_model=SessionInfo)
    async def create_session():
        mgr = app.state.manager
        sid = await mgr.create_session()
        return SessionInfo(**mgr.info(sid))

    @app.get("/session/{session_id}", response_model=SessionInfo)
    async def get_session(session_id):
        info = app.state.manager.info(session_id)
        if info is None:
            raise HTTPException(status_code=404, detail="no such session")
        return SessionInfo(**info)

    @app.delete("/session/{session_id}")
    async def dispose_session(session_id):
        await app.state.manager.dispose_session(session_id)
        return {"status": "disposed", "session_id": session_id}

    @app.post("/inspect", response_model=InspectResult)
    async def inspect(req: InspectRequest):
        mgr = app.state.manager
        page = _page_or_404(req.session_id)
        status = None
        if req.navigate:
            resp = await page.goto(req.url, wait_until="domcontentloaded", timeout=60_000)
            status = resp.status if resp is not None else None
        signals = await extract_signals(page, http_status=status)
        blocker = classify_page(signals)
        if blocker == "ambiguous":
            if await follow_apply_link_if_present(page):
                signals = await extract_signals(page, http_status=status)
                blocker = classify_page(signals)
        if blocker == "ambiguous":
            await wait_for_fillable_content(page)
            signals = await extract_signals(page, http_status=status)
            blocker = classify_page(signals)
        shot = mgr.artifact_path(req.session_id, "inspect.png")
        await page.screenshot(path=shot)
        if blocker is not None:
            return InspectResult(blocker=blocker, screenshot_path=shot)
        schema = await extract_form_schema(page)
        return InspectResult(form_schema=schema, screenshot_path=shot)

    @app.post("/content", response_model=ContentResult)
    async def content(req: ContentRequest):
        page = _page_or_404(req.session_id)
        await page.goto(req.url, wait_until="domcontentloaded", timeout=60_000)
        html = await page.content()
        return ContentResult(html=html)

    @app.post("/pdf")
    async def render_pdf(req: PdfRequest):
        pdf = await app.state.manager.render_pdf(req.html)
        return Response(content=pdf, media_type="application/pdf")

    @app.post("/fill", response_model=FillResult)
    async def fill(req: FillRequest):
        mgr = app.state.manager
        page = _page_or_404(req.session_id)
        shot = mgr.artifact_path(req.session_id, "fill.png")
        return await fill_form(
            page, req.fields, resume_path=req.resume_path, screenshot_path=shot,
            consent_checks=req.consent_checks,
        )

    @app.post("/submit", response_model=SubmitResult)
    async def submit(req: SubmitRequest):
        mgr = app.state.manager
        page = _page_or_404(req.session_id)
        shot = mgr.artifact_path(req.session_id, "submit_confirm.png")
        return await submit_form(
            page, req.fields, resume_path=req.resume_path, screenshot_path=shot,
            consent_checks=req.consent_checks,
        )

    @app.post("/handoff", response_model=HandoffResult)
    async def handoff(req: HandoffRequest):
        """Создать persist-сессию и навигировать к URL для ручного взаимодействия.

        Предназначен для CAPTCHA/MFA — передаёт живой браузер человеку через noVNC.
        Физически НЕ делает submit (инвариант §3/§4 ТЗ).
        """
        mgr = app.state.manager
        sid = await mgr.create_session(persist=True)
        page = mgr.get_page(sid)
        await page.goto(req.url)
        novnc_url = build_novnc_url(os.environ.get("NOVNC_BASE_URL"), sid)
        return HandoffResult(session_id=sid, status="handoff", novnc_url=novnc_url)

    @app.post("/handoff/{session_id}/release")
    async def release_handoff(session_id: str):
        """Форсированно уничтожить handoff-сессию после завершения ручного взаимодействия."""
        mgr = app.state.manager
        if mgr.info(session_id) is None:
            raise HTTPException(status_code=404, detail="no such session")
        await mgr.dispose_session(session_id, force=True)
        return {"status": "released", "session_id": session_id}

    return app


app = create_app()
