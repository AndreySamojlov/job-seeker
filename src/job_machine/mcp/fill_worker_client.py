"""HTTP-клиент MCP к job-fill воркеру.

MCP-сервер локально не имеет /data и job-browser. fill_service.run_fill() локально
фейлится на hash_file('/data/resumes/...'). Делегируем вызов /fill/run воркеру —
тот имеет /data и job-browser в Docker-сети.

Порт job-fill пробросить туннелем (по умолчанию 8092:8082 или аналог).
"""
import httpx

from job_machine.fill.models import FillRunSummary


class FillWorkerClient:
    def __init__(self, base_url: str, http: httpx.Client | None = None,
                 timeout: float = 120.0):
        self._http = http or httpx.Client(base_url=base_url, timeout=timeout)

    def run_fill(self, limit: int = 10,
                 candidate_id: str | None = None) -> FillRunSummary:
        """POST /fill/run — запустить fill-прогон на воркере (у него /data + job-browser).

        candidate_id прокидывается в тело: воркер скоупит fill-очередь этим кандидатом."""
        resp = self._http.post(
            "/fill/run", json={"limit": limit, "candidate_id": candidate_id})
        resp.raise_for_status()
        return FillRunSummary.model_validate(resp.json())

    def resume_after_handoff(self, application_id: str, session_id: str) -> dict:
        """POST /fill/resume — продолжить fill в существующей handoff-сессии
        (после того как владелец вручную прошёл CAPTCHA/MFA)."""
        resp = self._http.post(
            "/fill/resume", json={"application_id": application_id, "session_id": session_id})
        resp.raise_for_status()
        return resp.json()

    def close(self) -> None:
        self._http.close()
