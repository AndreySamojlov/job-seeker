import httpx

from job_machine.discovery.models import RawHimalayasJob
from job_machine.http.retry import request_with_retry

HIMALAYAS_LIST_URL = "https://himalayas.app/jobs/api"


class HimalayasClient:
    """Клиент Himalayas Remote Jobs API (публичный, без ключа). ВАЖНО: list-ответ
    несёт только excerpt (короткий блёрб), НЕ полный текст вакансии — fetch_content
    отдаёт именно excerpt, это ограничение источника, не баг (см. шапку плана)."""

    def __init__(self, http_client: httpx.Client | None = None, timeout: float = 15.0):
        self._client = http_client or httpx.Client(timeout=timeout)
        self._cache: list[RawHimalayasJob] | None = None

    def _get(self, url: str, **kw) -> httpx.Response:
        return request_with_retry(self._client, "GET", url, **kw)

    def get_board_name(self, token: str) -> None:
        return None

    def list_jobs(self, token: str, query: dict | None = None) -> list[RawHimalayasJob]:
        params = {"limit": 200}
        resp = self._get(HIMALAYAS_LIST_URL, params=params)
        resp.raise_for_status()
        return [RawHimalayasJob.from_api(j) for j in resp.json().get("jobs", [])]

    def _ensure_cache(self) -> list[RawHimalayasJob]:
        if self._cache is None:
            self._cache = self.list_jobs("")
        return self._cache

    def check_job(self, url: str) -> str:
        try:
            jobs = self._ensure_cache()
        except httpx.HTTPError:
            return "error"
        return "live" if any(j.application_link == url for j in jobs) else "gone"

    def fetch_content(self, url: str) -> str | None:
        for j in self._ensure_cache():
            if j.application_link == url:
                return j.excerpt
        return None

    def close(self) -> None:
        self._client.close()
