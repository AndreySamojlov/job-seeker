import httpx

from job_machine.discovery.models import RawPinpointJob
from job_machine.http.retry import request_with_retry


class PinpointClient:
    """Клиент Pinpoint публичного JSON-фида (без авторизации, проба 2026-07-15).
    Список отдаёт весь борд одним ответом, включая полное description (как
    Recruitee) — отдельного per-posting detail-эндпоинта нет (проверено: и
    /postings/{id}.json, и per-slug .json отдают 404/406). fetch_content поэтому
    переиспользует list_jobs и матчит по url; token извлекается из хоста url.

    ВАЖНО: в отличие от Recruitee (у которого fetch_content — один GET на
    detail-эндпоинт на вакансию), здесь fetch_content — O(размер_борда) на КАЖДЫЙ
    вызов, т.к. пере-запрашивает список целиком. Для больших бордов при высокой
    частоте вызовов на одном токене стоит рассмотреть кэш на уровне вызывающего
    кода (triage/discovery-run) — не реализовано здесь, т.к. не требовалось
    текущим объёмом (спека)."""

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
        """Список не отдаёт имя компании — как Workable/Recruitee/SmartRecruiters,
        полагаемся на label из sources.json."""
        return None

    def list_jobs(self, token: str) -> list[RawPinpointJob]:
        resp = self._get(f"https://{token}.pinpointhq.com/postings.json")
        resp.raise_for_status()
        return [RawPinpointJob.from_api(j) for j in resp.json().get("data", [])]

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
        """None — борд-фид отдал 404 ИЛИ вакансия больше не встречается в списке
        (оба трактуются как 'больше нет', см. докстринг класса)."""
        token = (httpx.URL(url).host or "").split(".")[0]
        list_url = f"https://{token}.pinpointhq.com/postings.json"
        resp = self._get(list_url)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        for job in (RawPinpointJob.from_api(j) for j in resp.json().get("data", [])):
            if job.url == url:
                return job.description
        return None

    def close(self) -> None:
        self._client.close()
