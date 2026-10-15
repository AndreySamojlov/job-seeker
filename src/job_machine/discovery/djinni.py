import httpx

from job_machine.discovery.models import RawDjinniJob
from job_machine.discovery.rss import parse_rss_items
from job_machine.http.retry import request_with_retry

DJINNI_RSS_URL = "https://djinni.co/jobs/rss/"


class DjinniClient:
    """Клиент RSS-фида Djinni (публичный, без ключа). Нет company-поля в RSS —
    company всегда None (задокументировано в RawDjinniJob). Кэш на инстанс, как
    у JSON-агрегаторов."""

    def __init__(self, http_client: httpx.Client | None = None, timeout: float = 15.0):
        self._client = http_client or httpx.Client(timeout=timeout)
        self._cache: list[RawDjinniJob] | None = None

    def _get(self, url: str, **kw) -> httpx.Response:
        return request_with_retry(self._client, "GET", url, **kw)

    def get_board_name(self, token: str) -> None:
        return None

    def list_jobs(self, token: str, query: dict | None = None) -> list[RawDjinniJob]:
        resp = self._get(DJINNI_RSS_URL)
        resp.raise_for_status()
        return [RawDjinniJob.from_feed_item(f) for f in parse_rss_items(resp.text)]

    def _ensure_cache(self) -> list[RawDjinniJob]:
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
