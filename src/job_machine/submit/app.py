"""FastAPI submit worker. /submit/run — намеренно строим INACTIVE n8n флоу (устав §3)."""
import os

from fastapi import FastAPI, HTTPException

from job_machine.db.connection import connect
from job_machine.mcp import store as mcp_store
from job_machine.runtime import control as runtime_control
from job_machine.submit import service
from job_machine.submit import store
from job_machine.submit.browser_client import SubmitBrowserClient
from job_machine.submit.models import SubmitRunSummary


def _default_browser():
    return SubmitBrowserClient(
        base_url=os.environ.get("BROWSER_WORKER_URL", "http://job-browser:8080"))


def create_app(conn_factory=connect, browser_factory=_default_browser) -> FastAPI:
    app = FastAPI(title="job-machine submit worker")

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    def _require_submit_enabled(conn) -> None:
        """[SAFETY] Рубильник fail-closed: выключен — воркер не касается браузера."""
        if not runtime_control.is_submit_enabled(conn):
            raise HTTPException(status_code=503, detail="submit_disabled")

    @app.post("/submit/run", response_model=SubmitRunSummary)
    def submit_run(body: dict | None = None):
        limit = (body or {}).get("limit", 5)
        conn = conn_factory()
        browser = None
        try:
            _require_submit_enabled(conn)
            browser = browser_factory()
            return service.run_submit(conn, browser, limit)
        finally:
            close = getattr(browser, "close", None)
            if callable(close):
                close()
            conn.close()

    @app.post("/submit/one", response_model=SubmitRunSummary)
    def submit_one(body: dict):
        """Submit ровно одной одобренной заявки по id (per-id путь кокпита/MCP).

        Тот же трипл-gate, что /submit/run (claim_application + submit-гарды). Вынесен
        в воркер, т.к. локальный MCP не имеет /data для чтения manifest/резюме (§3).
        """
        application_id = body["application_id"]
        conn = conn_factory()
        browser = None
        try:
            _require_submit_enabled(conn)
            browser = browser_factory()
            return service.run_submit_one(conn, browser, application_id)
        finally:
            close = getattr(browser, "close", None)
            if callable(close):
                close()
            conn.close()

    @app.post("/submit/recover")
    def submit_recover():
        """Намеренно работает и при выключенном сабмите: это чистка БД, не подача.

        Ручная ручка, а не единственный путь: штатное расклинивание делает сам прогон
        подачи (service._recover_stale) — эндпоинт нужен, когда сабмит выключен
        рубильником и прогонов не будет, а зависшее надо разобрать сейчас.
        """
        conn = conn_factory()
        try:
            summary = store.recover_stale_attempts(conn)
            conn.commit()
            return summary
        finally:
            conn.close()

    @app.get("/application/{application_id}/detail")
    def application_detail(application_id: str):
        """Детали заявки + текст disclosed-summary для презентации перед одобрением.

        Summary-артефакт лежит на /data (смонтирован у воркера); локальный MCP его не
        видит, поэтому чтение делегируется сюда. Браузер не нужен — только conn + /data.
        """
        conn = conn_factory()
        try:
            return mcp_store.load_application_detail(conn, application_id)
        finally:
            conn.close()

    return app


app = create_app()
