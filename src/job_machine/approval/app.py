"""FastAPI approval worker. Оператор: /approval/request (создать токен) → /approval/approve или /reject."""
from fastapi import FastAPI

from job_machine.approval import service, store
from job_machine.db.connection import connect


def create_app(conn_factory=connect) -> FastAPI:
    app = FastAPI(title="job-machine approval worker")

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    @app.post("/approval/request")
    def approval_request(body: dict | None = None):
        limit = (body or {}).get("limit", 10)
        conn = conn_factory()
        try:
            return service.process_approval_request(conn, limit)
        finally:
            conn.close()

    @app.post("/approval/approve")
    def approval_approve(body: dict):
        application_id = body["application_id"]
        conn = conn_factory()
        try:
            ok = store.approve(conn, application_id)
            conn.commit()
        finally:
            conn.close()
        return {"approved": ok, "application_id": application_id}

    @app.post("/approval/reject")
    def approval_reject(body: dict):
        application_id = body["application_id"]
        reason = body.get("reason", "")
        conn = conn_factory()
        try:
            ok = store.reject(conn, application_id, reason)
            conn.commit()
        finally:
            conn.close()
        return {"rejected": ok, "application_id": application_id}

    @app.get("/approval/status/{application_id}")
    def approval_status(application_id: str):
        conn = conn_factory()
        try:
            rec = store.load_by_application(conn, application_id)
        finally:
            conn.close()
        if rec is None:
            return {"application_id": application_id, "approval_status": None}
        return {
            "application_id": application_id,
            "approval_status": rec["approval_status"],
            "payload_hash": rec["payload_hash"],
            "expires_at": str(rec["expires_at"]) if rec.get("expires_at") else None,
            "approved_at": str(rec["approved_at"]) if rec.get("approved_at") else None,
        }

    return app


app = create_app()
