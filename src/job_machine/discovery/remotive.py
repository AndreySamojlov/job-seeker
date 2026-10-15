import httpx

from job_machine.discovery.models import RawRemotiveJob
from job_machine.http.retry import request_with_retry

REMOTIVE_LIST_URL = "https://remotive.com/api/remote-jobs"

# Их ToS прямо просит не чаще 4 запросов/день — вызывающий код (discovery worker)
# ОБЯЗАН проверить throttle.should_skip_fetch("remotive", MIN_INTERVAL_SECONDS)
# перед вызовом list_jobs (см. Task 4 Step 12 — точка интеграции в discovery runner).
MIN_INTERVAL_SECONDS = 6 * 3600


class RemotiveClient:
    """Клиент Remotive Remote Jobs API (публичный, без ключа, жёсткий rate limit
    их же ToS — см. MIN_INTERVAL_SECONDS)."""

    def __init__(self, http_client: httpx.Client | None = None, timeout: float = 15.0):
        self._client = http_client or httpx.Client(timeout=timeout)
        self._cache: list[RawRemotiveJob] | None = None

    def _get(self, url: str, **kw) -> httpx.Response:
        return request_with_retry(self._client, "GET", url, **kw)

    def get_board_name(self, token: str) -> None:
        return None

    def list_jobs(self, token: str, query: dict | None = None) -> list[RawRemotiveJob]:
        resp = self._get(REMOTIVE_LIST_URL)
        resp.raise_for_status()
        return [RawRemotiveJob.from_api(j) for j in resp.json().get("jobs", [])]

    def _ensure_cache(self) -> list[RawRemotiveJob]:
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
