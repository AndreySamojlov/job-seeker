import httpx

from job_machine.discovery.models import RawRecruiteeJob
from job_machine.http.retry import request_with_retry


class RecruiteeClient:
    """Клиент Recruitee публичного Offers API (без авторизации). Список отдаёт весь
    борд одним ответом (в т.ч. полный текст description — тяжёлый payload,
    ~26 КБ/вакансия, спека §7), но normalize сохраняет только нужные поля; полный
    текст перечитывается точечно на триаже через detail-эндпоинт."""

    def __init__(self, http_client: httpx.Client | None = None,
                 timeout: float = 15.0, sleep=None):
        self._client = http_client or httpx.Client(timeout=timeout)
        self._sleep = sleep

    def _get(self, url: str, **kw) -> httpx.Response:
        kwargs = dict(kw)
        if self._sleep is not None:
            kwargs["sleep"] = self._sleep
        return request_with_retry(self._client, "GET", url, **kwargs)

    def get_board_name(self, token: str) -> None:
        """Имя компании (company_name) есть в offer, но пустой борд не гарантирует
        хотя бы один offer — не полагаемся, используем label из sources.json."""
        return None

    def list_jobs(self, token: str) -> list[RawRecruiteeJob]:
        resp = self._get(f"https://{token}.recruitee.com/api/offers/")
        resp.raise_for_status()
        return [RawRecruiteeJob.from_api(j) for j in resp.json().get("offers", [])]

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
        """None — только подтверждённый 404. Detail оборачивает offer в ключ 'offer'."""
        resp = self._get(url)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json().get("offer", {}).get("description")

    def close(self) -> None:
        self._client.close()
