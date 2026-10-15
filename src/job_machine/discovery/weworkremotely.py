import httpx

from job_machine.discovery.models import RawWwrJob
from job_machine.discovery.rss import parse_rss_items
from job_machine.http.retry import request_with_retry

WWR_RSS_URL = "https://weworkremotely.com/remote-jobs.rss"


class WwrClient:
    """Клиент RSS-фида We Work Remotely (публичный, без ключа). Remote-only борд
    по определению — work_mode всегда 'remote' (normalize.py). Company парсится
    из title (формат 'Компания: Заголовок' — RawWwrJob.from_feed_item)."""

    def __init__(self, http_client: httpx.Client | None = None, timeout: float = 15.0):
        self._client = http_client or httpx.Client(timeout=timeout)
        self._cache: list[RawWwrJob] | None = None

    def _get(self, url: str, **kw) -> httpx.Response:
        return request_with_retry(self._client, "GET", url, **kw)

    def get_board_name(self, token: str) -> None:
        return None

    def list_jobs(self, token: str, query: dict | None = None) -> list[RawWwrJob]:
        resp = self._get(WWR_RSS_URL)
        resp.raise_for_status()
        return [RawWwrJob.from_feed_item(f) for f in parse_rss_items(resp.text)]

    def _ensure_cache(self) -> list[RawWwrJob]:
        if self._cache is None:
            self._cache = self.list_jobs("")
        return self._cache

    def check_job(self, url: str) -> str:
        try:
            jobs = self._ensure_cache()
        except httpx.HTTPError:
            return "error"
        return "live" if any(j.link == url for j in jobs) else "gone"

    def fetch_content(self, url: str) -> str | None:
        for j in self._ensure_cache():
            if j.link == url:
                return j.description
        return None

    def close(self) -> None:
        self._client.close()
