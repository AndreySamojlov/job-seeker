import httpx

from job_machine.discovery.models import RawWorkableJob
from job_machine.http.retry import request_with_retry

WORKABLE_LIST_BASE = "https://apply.workable.com/api/v3/accounts"
WORKABLE_DETAIL_BASE = "https://apply.workable.com/api/v1/accounts"


class WorkableClient:
    """Клиент Workable публичного Jobs API (без авторизации, недокументированный,
    но стабильно наблюдаемый — проба 2026-07-03). list — POST с пагинацией через
    непрозрачный nextPage-токен из тела ответа (не query-параметр); detail — GET по
    shortcode."""

    MAX_PAGES = 50  # анти-цикл на аномальный/бесконечный nextPage (реальные борды: единицы-десятки страниц)

    def __init__(self, http_client: httpx.Client | None = None,
                 timeout: float = 15.0, sleep=None):
        self._client = http_client or httpx.Client(timeout=timeout)
        self._sleep = sleep

    def _get(self, url: str, **kw) -> httpx.Response:
        kwargs = dict(kw)
        if self._sleep is not None:
            kwargs["sleep"] = self._sleep
        return request_with_retry(self._client, "GET", url, **kwargs)

    def _post(self, url: str, json_body: dict) -> httpx.Response:
        kwargs = {"json": json_body}
        if self._sleep is not None:
            kwargs["sleep"] = self._sleep
        return request_with_retry(self._client, "POST", url, **kwargs)

    def get_board_name(self, token: str) -> None:
        """Workable list/detail не отдают имя компании — всегда None (label из sources.json)."""
        return None

    def list_jobs(self, token: str) -> list[RawWorkableJob]:
        url = f"{WORKABLE_LIST_BASE}/{token}/jobs"
        jobs: list[RawWorkableJob] = []
        body: dict = {}
        for _ in range(self.MAX_PAGES):
            resp = self._post(url, body)
            resp.raise_for_status()
            data = resp.json()
            jobs.extend(RawWorkableJob.from_api(j) for j in data.get("results", []))
            next_token = data.get("nextPage")
            if not next_token:
                break
            body = {"token": next_token}
        return jobs

    def check_job(self, url: str) -> str:
        """'live' (200) / 'gone' (404) / 'error' (прочее/сеть)."""
        try:
            resp = self._get(url)
        except httpx.HTTPError:
            return "error"
        if resp.status_code == 200:
            return "live"
        if resp.status_code == 404:
            return "gone"
        return "error"

    def fetch_content(self, url: str) -> str | None:
        """None — только подтверждённый 404. Прочее пробрасывается исключением
        (triage должен ретраить позже, а не хоронить вакансию)."""
        resp = self._get(url)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json().get("description")

    def close(self) -> None:
        self._client.close()
