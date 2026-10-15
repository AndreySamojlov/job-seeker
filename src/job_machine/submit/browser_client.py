"""Submit-клиент браузер-воркера: расширяет BrowserClient методом .submit()."""
import httpx

from job_machine.browser.schema import SubmitResult
from job_machine.fill.browser_client import BrowserClient


class SubmitBrowserClient(BrowserClient):
    def __init__(self, base_url, http: httpx.Client | None = None, timeout: float = 180.0):
        # 180s: fill + networkidle wait на медленных ATS-формах занимает больше дефолтных 120s
        super().__init__(base_url, http=http, timeout=timeout)

    def submit(self, session_id: str, fields: dict,
               resume_path: str | None = None,
               consent_checks: list | None = None) -> SubmitResult:
        """POST /submit: fill + click submit + capture confirmation."""
        resp = self._http.post("/submit", json={
            "session_id": session_id,
            "fields": fields,
            "resume_path": resume_path,
            "consent_checks": consent_checks or [],
        })
        resp.raise_for_status()
        return SubmitResult.model_validate(resp.json())
