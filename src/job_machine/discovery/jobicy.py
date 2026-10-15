import httpx

from job_machine.discovery.models import RawJobicyJob
from job_machine.http.retry import request_with_retry

JOBICY_LIST_URL = "https://jobicy.com/api/v2/remote-jobs"


class JobicyClient:
    """Клиент Jobicy Remote Jobs API (публичный, без ключа). Их policy — не чаще
    раза в час (min-interval применяется на уровне вызывающего кода через
    discovery/throttle.py, не внутри клиента). Нет detail-эндпоинта — кэш на
    инстанс, как у ArbeitnowClient."""

    def __init__(self, http_client: httpx.Client | None = None, timeout: float = 15.0):
        self._client = http_client or httpx.Client(timeout=timeout)
        self._cache: list[RawJobicyJob] | None = None

    def _get(self, url: str, **kw) -> httpx.Response:
        return request_with_retry(self._client, "GET", url, **kw)

    def get_board_name(self, token: str) -> None:
        return None

    def list_jobs(self, token: str, query: dict | None = None) -> list[RawJobicyJob]:
        params = {"count": 100}
        if query:
            if query.get("geo"):
                params["geo"] = query["geo"]
            if query.get("tag"):
                params["tag"] = query["tag"]
        resp = self._get(JOBICY_LIST_URL, params=params)
        resp.raise_for_status()
        return [RawJobicyJob.from_api(j) for j in resp.json().get("jobs", [])]

    def _ensure_cache(self) -> list[RawJobicyJob]:
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
