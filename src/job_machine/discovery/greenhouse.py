import httpx

from job_machine.discovery.models import RawGreenhouseJob
from job_machine.http.retry import request_with_retry

GH_BASE = "https://boards-api.greenhouse.io/v1/boards"


class GreenhouseClient:
    """Клиент Greenhouse Job Board API (публичный, без авторизации)."""

    def __init__(self, http_client: httpx.Client | None = None,
                 base_url: str = GH_BASE, timeout: float = 15.0,
                 sleep=None):
        self._client = http_client or httpx.Client(timeout=timeout)
        self._base = base_url.rstrip("/")
        self._sleep = sleep

    def _get(self, url: str) -> httpx.Response:
        kwargs = {} if self._sleep is None else {"sleep": self._sleep}
        return request_with_retry(self._client, "GET", url, **kwargs)

    def get_board_name(self, token: str) -> str | None:
        resp = self._get(f"{self._base}/{token}")
        if resp.status_code == 200:
            return resp.json().get("name")
        return None

    def list_jobs(self, token: str) -> list[RawGreenhouseJob]:
        resp = self._get(f"{self._base}/{token}/jobs")
        resp.raise_for_status()
        return [RawGreenhouseJob.from_api(j) for j in resp.json().get("jobs", [])]

    def check_job(self, api_url: str) -> str:
        """Проверить per-job endpoint: 'live' (200) / 'gone' (404) / 'error' (прочее)."""
        try:
            resp = self._get(api_url)
        except httpx.HTTPError:
            return "error"
        if resp.status_code == 200:
            return "live"
        if resp.status_code == 404:
            return "gone"
        return "error"

    def fetch_content(self, api_url: str) -> str | None:
        """Полный текст вакансии: per-job GH endpoint отдаёт поле content (HTML).
        None — только подтверждённый 404 (вакансия точно снята). Сетевые ошибки и
        прочие статусы (5xx/429 после исчерпанных ретраев) пробрасываются исключением:
        вызывающий код (triage) должен ретраить позже, а не считать вакансию мёртвой."""
        resp = self._get(api_url)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json().get("content")

    def close(self) -> None:
        self._client.close()
