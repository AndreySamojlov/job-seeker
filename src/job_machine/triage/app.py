from fastapi import FastAPI

from job_machine.db.connection import connect
from job_machine.discovery.greenhouse import GreenhouseClient
from job_machine.mcp.store import list_candidates
from job_machine.triage import service
from job_machine.triage.models import TriageVerdict


def create_app(conn_factory=connect, client_factory=GreenhouseClient) -> FastAPI:
    app = FastAPI(title="job-machine triage worker")

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    @app.post("/triage/pull")
    def pull(body: dict | None = None):
        body = body or {}
        limit = body.get("limit", 25)
        candidate_id = body.get("candidate_id", "andrey-s")
        conn = conn_factory()
        client = client_factory()
        try:
            summary = service.build_triage_inputs(conn, client, candidate_id, limit)
        finally:
            client.close()
            conn.close()
        return {
            "count": len(summary.inputs),
            "quick_skipped": summary.quick_skipped,
            "skipped_no_content": summary.skipped_no_content,
            "inputs": [i.model_dump() for i in summary.inputs],
        }

    @app.post("/triage/pull_all")
    def pull_all(body: dict | None = None):
        """Триаж-inputs по ВСЕМ активным кандидатам за один вызов (для scheduled
        n8n-флоу). Каждый input тегирован candidate_id → Apply применяет вердикт
        правильному кандидату. limit трактуется как лимит НА КАНДИДАТА."""
        body = body or {}
        limit = body.get("limit", 25)
        conn = conn_factory()
        client = client_factory()
        try:
            candidate_ids = [c["candidate_id"] for c in list_candidates(conn)]
            summary = service.build_triage_inputs_all(conn, client, candidate_ids, limit)
        finally:
            client.close()
            conn.close()
        return {
            "count": len(summary.inputs),
            "quick_skipped": summary.quick_skipped,
            "skipped_no_content": summary.skipped_no_content,
            "inputs": [i.model_dump() for i in summary.inputs],
        }

    @app.post("/triage/apply")
    def apply(verdict: TriageVerdict, candidate_id: str = "andrey-s"):
        conn = conn_factory()
        try:
            route = service.apply_triage(conn, verdict, candidate_id)
        finally:
            conn.close()
        return {"vacancy_id": verdict.vacancy_id, "route": route}

    return app


app = create_app()
