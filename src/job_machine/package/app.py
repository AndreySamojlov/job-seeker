"""FastAPI воркер сборки пакетов. Маршрутов submit/fill/браузера НЕТ намеренно
(устав §3, ТЗ §4) — submit появится в Плане 6 под approval-токеном."""
import os

from fastapi import FastAPI
from pydantic import BaseModel

from job_machine.db.connection import connect
from job_machine.package import service

DEFAULT_BASE_DIR = os.environ.get("PACKAGE_BASE_DIR", "applications")


class BuildRequest(BaseModel):
    limit: int = 10
    # candidate_id опционален: n8n auto-свип без него → глобальный FIFO по всем
    # (обратная совместимость); кокпит передаёт явно → очередь скоупится кандидатом.
    candidate_id: str | None = None


def create_app(conn_factory=connect) -> FastAPI:
    app = FastAPI(title="job-machine package builder")

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    @app.post("/package/build")
    def build(req: BuildRequest):
        # Упаковка идёт ЗДЕСЬ (у воркера /data → PACKAGE_BASE_DIR=/data/applications,
        # читаемо fill-воркером), НЕ локально через MCP: локальный run_package пишет
        # Windows-пути applications\..., нечитаемые lab-do (→ broken_flow).
        conn = conn_factory()
        try:
            built = service.run_package_build(conn, DEFAULT_BASE_DIR, req.limit,
                                              req.candidate_id)
        finally:
            conn.close()
        return {"built": built}

    return app


app = create_app()
