"""FastAPI dashboard worker — read-only обзор воронки.

GET-only по построению: не импортирует submit/browser-клиенты, submit недостижим
(§3/§4 ТЗ). Данные читаются на каждый GET /, рендерятся server-side, страница
сама перезапрашивается через meta-refresh.
"""
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from job_machine.db.connection import connect
from job_machine.dashboard import store, render
from job_machine.mcp import store as mcp_store


def create_app(conn_factory=connect) -> FastAPI:
    app = FastAPI(title="job-machine dashboard")

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    @app.get("/", response_class=HTMLResponse)
    def dashboard():
        conn = conn_factory()
        try:
            funnel = store.count_funnel(conn)
            blockers = store.count_blockers(conn)
            ready = mcp_store.query_ready_queue_all(conn, limit=50)
        finally:
            conn.close()
        return render.render_dashboard(
            funnel, blockers, ready, generated_at=datetime.now(timezone.utc)
        )

    return app


app = create_app()
