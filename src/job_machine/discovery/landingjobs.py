import httpx

from job_machine.discovery.models import RawLandingJobsJob
from job_machine.http.retry import request_with_retry

LANDING_JOBS_LIST_URL = "https://landing.jobs/api/v1/jobs"


class LandingJobsClient:
    """Клиент Landing.jobs API (публичный, без ключа для чтения — auth нужен
    только user-specific эндпоинтам, которые здесь не используются). Ответ —
    плоский JSON-массив, без обёртки. Нет отдельного company-поля — извлекается
    из URL (сегмент после /at/, RawLandingJobsJob.from_api)."""

    def __init__(self, http_client: httpx.Client | None = None, timeout: float = 15.0):
        self._client = http_client or httpx.Client(timeout=timeout)
        self._cache: list[RawLandingJobsJob] | None = None

    def _get(self, url: str, **kw) -> httpx.Response:
        return request_with_retry(self._client, "GET", url, **kw)

    def get_board_name(self, token: str) -> None:
        return None

    def list_jobs(self, token: str, query: dict | None = None) -> list[RawLandingJobsJob]:
        resp = self._get(LANDING_JOBS_LIST_URL)
        resp.raise_for_status()
        return [RawLandingJobsJob.from_api(j) for j in resp.json()]

    def _ensure_cache(self) -> list[RawLandingJobsJob]:
        if self._cache is None:
            self._cache = self.list_jobs("")
        return self._cache

    def check_job(self, url: str) -> str:
        try:
            jobs = self._ensure_cache()
        except httpx.HTTPError:
            return "error"
        return "live" if any(j.url == url for j in jobs) else "gone"

    def fetch_content(self, url: str) -> str | None:
        for j in self._ensure_cache():
            if j.url == url:
                return j.description
        return None

    def close(self) -> None:
        self._client.close()
