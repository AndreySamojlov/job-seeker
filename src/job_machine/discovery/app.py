from dataclasses import asdict

from fastapi import FastAPI

from job_machine.db.connection import connect
from job_machine.discovery import service
from job_machine.discovery.greenhouse import GreenhouseClient
from job_machine.discovery.sources import load_sources


def create_app(conn_factory=connect, client_factory=GreenhouseClient,
               sources_loader=load_sources) -> FastAPI:
    app = FastAPI(title="job-machine discovery worker")

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    @app.post("/discover")
    def discover(body: dict | None = None):
        explicit_boards = (body or {}).get("boards")
        conn = conn_factory()
        try:
            if explicit_boards:
                # Legacy explicit-boards путь — один ATS (Greenhouse), для ручных проб.
                client = client_factory()
                try:
                    summary = service.run_discovery(conn, client, explicit_boards)
                finally:
                    client.close()
            else:
                # Дефолт — мульти-ATS реестр (config/sources.json): GH+Lever+Ashby.
                summary = service.run_discovery_multi(conn, sources_loader())
        finally:
            conn.close()
        return asdict(summary)

    @app.post("/verify")
    def verify(body: dict | None = None):
        limit = (body or {}).get("limit", 50)
        conn = conn_factory()
        client = client_factory()
        try:
            summary = service.run_verify(conn, client, limit)
        finally:
            client.close()
            conn.close()
        return asdict(summary)

    return app


app = create_app()
