"""HTTP-клиент MCP к job-submit воркеру.

MCP-сервер крутится локально (Windows): у него нет /data и Docker-DNS, поэтому он НЕ
исполняет submit и НЕ читает disclosed-summary-артефакт сам. Эти шаги делегируются
воркеру job-submit (у него смонтирован /data и резолвится job-browser). Клиент —
тонкий httpx-фасад (как fill/browser_client.py), тестируемый через MockTransport.

Трипл-gate (§3) живёт в воркере (submit/gate.py + claim_application); клиент его не
ослабляет — он лишь переносит вызов run_submit_one за сетевую границу.
"""
import httpx

from job_machine.submit.models import SubmitRunSummary


class SubmitWorkerClient:
    def __init__(self, base_url: str, http: httpx.Client | None = None,
                 timeout: float = 300.0):
        # 300s: submit = inspect + fill + click + networkidle на медленных ATS-формах.
        self._http = http or httpx.Client(base_url=base_url, timeout=timeout)

    def submit_one(self, application_id: str) -> SubmitRunSummary:
        """POST /submit/one — submit ровно одной одобренной заявки (трипл-gate в воркере)."""
        resp = self._http.post("/submit/one", json={"application_id": application_id})
        resp.raise_for_status()
        return SubmitRunSummary.model_validate(resp.json())

    def get_application_detail(self, application_id: str) -> dict:
        """GET /application/{id}/detail — детали + disclosed summary (читает /data воркер)."""
        resp = self._http.get(f"/application/{application_id}/detail")
        resp.raise_for_status()
        return resp.json()

    def close(self) -> None:
        self._http.close()
