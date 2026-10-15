"""HTTP-API fill-воркера (FastAPI). Маршрута submit/browser НЕТ намеренно (устав §3).

Браузер-воркер дёргается как HTTP-зависимость (BROWSER_WORKER_URL). n8n триггерит /fill/run.
/fill/resume — продолжить fill в существующей handoff-сессии после ручной CAPTCHA/MFA
(вызывается MCP-тулом resume_fill, не n8n).
"""

import os

from fastapi import FastAPI
from pydantic import BaseModel

from job_machine.db.connection import connect
from job_machine.fill import service
from job_machine.fill.browser_client import BrowserClient


class ResumeRequest(BaseModel):
    application_id: str
    session_id: str


def _default_browser() -> BrowserClient:
    return BrowserClient(base_url=os.environ.get("BROWSER_WORKER_URL", "http://job-browser:8080"))


def create_app(conn_factory=connect, browser_factory=_default_browser) -> FastAPI:
    app = FastAPI(title="job-machine fill worker")

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    @app.post("/fill/run")
    def fill_run(body: dict | None = None):
        limit = (body or {}).get("limit", 10)
        # candidate_id — опционален: n8n-триггер без него → глобальный свип (совместимость);
        # кокпит передаёт явно → fill-очередь скоупится этим кандидатом.
        candidate_id = (body or {}).get("candidate_id")
        conn = conn_factory()
        browser = browser_factory()
        try:
            summary = service.run_fill(conn, browser, limit, candidate_id)
        finally:
            close = getattr(browser, "close", None)
            if callable(close):
                close()
            conn.close()
        return summary.model_dump()

    @app.post("/fill/resume")
    def fill_resume(body: ResumeRequest):
        application_id = body.application_id
        session_id = body.session_id
        conn = conn_factory()
        browser = browser_factory()
        try:
            return service.resume_after_handoff(conn, browser, application_id, session_id)
        finally:
            close = getattr(browser, "close", None)
            if callable(close):
                close()
            conn.close()

    @app.post("/fill/agent-context")
    def agent_context(body: ResumeRequest):
        conn = conn_factory()
        try:
            return service.agent_fill_context(conn, body.application_id, body.session_id)
        finally:
            conn.close()

    return app


app = create_app()
