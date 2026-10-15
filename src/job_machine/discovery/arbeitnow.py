import time

import httpx

from job_machine.discovery.models import RawArbeitnowJob
from job_machine.http.retry import request_with_retry

ARBEITNOW_LIST_URL = "https://www.arbeitnow.com/api/job-board-api"


class ArbeitnowClient:
    """Клиент Arbeitnow Job Board API (публичный, без ключа). Реальный заголовок
    ответа X-Ratelimit-Limit: 5 (не в доке, подтверждено живым fetch 2026-07-05) —
    троттлим между страницами. Нет detail-эндпоинта — check_job/fetch_content
    работают по кэшу одного list_jobs() на весь инстанс (см. спека §3)."""

    MAX_PAGES = 20
    PAGE_SLEEP_SECONDS = 15.0

    def __init__(self, http_client: httpx.Client | None = None,
                 timeout: float = 15.0, sleep=None):
        self._client = http_client or httpx.Client(timeout=timeout)
        self._sleep = sleep or time.sleep
        self._cache: list[RawArbeitnowJob] | None = None

    def _get(self, url: str, **kw) -> httpx.Response:
        return request_with_retry(self._client, "GET", url, **kw)

    def get_board_name(self, token: str) -> None:
        """Arbeitnow — агрегатор многих компаний, у самого источника нет 'имени'."""
        return None

    def list_jobs(self, token: str, query: dict | None = None) -> list[RawArbeitnowJob]:
        params: dict = {}
        if query and query.get("remote_only"):
            params["remote"] = "true"
        jobs: list[RawArbeitnowJob] = []
        page = 1
        for _ in range(self.MAX_PAGES):
            resp = self._get(ARBEITNOW_LIST_URL, params={**params, "page": page})
            resp.raise_for_status()
            data = resp.json()
            jobs.extend(RawArbeitnowJob.from_api(j) for j in data.get("data", []))
            next_link = (data.get("links") or {}).get("next")
            if not next_link:
                break
            page += 1
            self._sleep(self.PAGE_SLEEP_SECONDS)
        return jobs

    def _ensure_cache(self) -> list[RawArbeitnowJob]:
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
