"""HTTP-API резюме-воркера (FastAPI). Маршрута submit НЕТ намеренно (устав §3, §4 non-goals).

/resume/pull — детерминированный отбор → запрос фразинга для n8n.
/resume/apply — применить (LLM) фразинг: verify → render → PDF → запись.
/resume/run   — детерминированный floor без n8n (verbatim-фразинг), для smoke.
"""
import os

from fastapi import FastAPI

from job_machine.cloud.store import load_cloud
from job_machine.db.connection import connect
from job_machine.resume import selector, service, store
from job_machine.resume.models import ResumePhrasing
from job_machine.resume.pdf_client import PdfClient


def _default_pdf() -> PdfClient:
    return PdfClient(base_url=os.environ.get("BROWSER_WORKER_URL", "http://job-browser:8080"))


def create_app(conn_factory=connect, pdf_factory=_default_pdf) -> FastAPI:
    app = FastAPI(title="job-machine resume worker")
    base_dir = os.environ.get("RESUME_DIR", "/data/resumes")

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    @app.post("/resume/pull")
    def resume_pull(body: dict | None = None):
        limit = (body or {}).get("limit", 10)
        conn = conn_factory()
        try:
            items = []
            for row in store.pull_needs_resume(conn, limit):
                sel = selector.build_selection(row["application_id"], row["role"],
                                               row["hard_requirements"],
                                               load_cloud(conn, row["candidate_id"]),
                                               candidate_name=row["candidate_name"],
                                               candidate_id=row["candidate_id"])
                jd = service.build_jd_summary(row)
                items.append(selector.phrasing_request(sel, jd_summary=jd).model_dump())
        finally:
            conn.close()
        return {"count": len(items), "items": items}

    @app.post("/resume/apply")
    def resume_apply(phrasing: ResumePhrasing):
        conn = conn_factory()
        pdf = pdf_factory()
        try:
            art = service.apply_phrasing(conn, pdf, base_dir, phrasing)
        finally:
            close = getattr(pdf, "close", None)
            if callable(close):
                close()
            conn.close()
        if art is None:
            return {"status": "skipped", "reason": "no pending application"}
        return art.model_dump()

    @app.post("/resume/run")
    def resume_run(body: dict | None = None):
        limit = (body or {}).get("limit", 10)
        conn = conn_factory()
        pdf = pdf_factory()
        try:
            built = service.run_resume(conn, pdf, base_dir, limit)
        finally:
            close = getattr(pdf, "close", None)
            if callable(close):
                close()
            conn.close()
        return {"built": built}

    return app


app = create_app()
