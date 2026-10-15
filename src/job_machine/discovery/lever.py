import httpx

from job_machine.discovery.models import RawLeverJob
from job_machine.http.retry import request_with_retry

LEVER_BASE = "https://api.lever.co/v0/postings"
LEVER_BASE_EU = "https://api.eu.lever.co/v0/postings"


def _eu_variant(url: str) -> str | None:
    """URL на api.eu.lever.co вместо api.lever.co — None, если хост не совпадает.
    EU data-residency борды (напр. Quadcode/XM Group/CoinsPaid) 404-ят на глобальном
    API и живут только на api.eu.lever.co — без этого выглядят мёртвыми навсегда."""
    if "https://api.lever.co/" not in url:
        return None
    return url.replace("https://api.lever.co/", "https://api.eu.lever.co/", 1)


class LeverClient:
    """Клиент Lever публичного Postings API (без авторизации). При 404 на глобальном
    хосте транспарентно повторяет запрос на api.eu.lever.co (EU data-residency)
    прежде чем считать борд/вакансию мёртвыми."""

    def __init__(
        self,
        http_client: httpx.Client | None = None,
        base_url: str = LEVER_BASE,
        timeout: float = 15.0,
        sleep=None,
    ):
        self._client = http_client or httpx.Client(timeout=timeout)
        self._base = base_url.rstrip("/")
        self._sleep = sleep

    def _get(self, url: str, **params_kwargs) -> httpx.Response:
        kwargs = dict(params_kwargs)
        if self._sleep is not None:
            kwargs["sleep"] = self._sleep
        return request_with_retry(self._client, "GET", url, **kwargs)

    def get_board_name(self, token: str) -> None:
        """Lever публичный API не раскрывает имя компании — всегда None."""
        return None

    def list_jobs(self, token: str) -> list[RawLeverJob]:
        resp = self._get(f"{self._base}/{token}", params={"mode": "json"})
        if resp.status_code == 404 and self._base == LEVER_BASE:
            resp = self._get(f"{LEVER_BASE_EU}/{token}", params={"mode": "json"})
        resp.raise_for_status()
        return [RawLeverJob.from_api(j) for j in resp.json()]

    def check_job(self, url: str) -> str:
        """Проверить URL вакансии: 'live' (200) / 'gone' (404) / 'error' (прочее/сеть)."""
        try:
            resp = self._get(url)
            if resp.status_code == 404:
                eu_url = _eu_variant(url)
                if eu_url:
                    resp = self._get(eu_url)
        except httpx.HTTPError:
            return "error"
        if resp.status_code == 200:
            return "live"
        if resp.status_code == 404:
            return "gone"
        return "error"

    def fetch_content(self, url: str) -> str | None:
        """Получить контент вакансии (поле descriptionPlain/description). None — только
        подтверждённый 404 (на обоих хостах). Сетевые ошибки и прочие статусы
        пробрасываются исключением — вызывающий код (triage) должен ретраить позже,
        а не считать вакансию мёртвой."""
        resp = self._get(url)
        if resp.status_code == 404:
            eu_url = _eu_variant(url)
            if eu_url:
                resp = self._get(eu_url)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        data = resp.json()
        return data.get("descriptionPlain") or data.get("description")

    def close(self) -> None:
        self._client.close()
