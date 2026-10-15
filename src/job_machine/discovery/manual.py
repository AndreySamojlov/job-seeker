import httpx

from job_machine.http.retry import request_with_retry

USER_AGENT = "job-machine-manual/1.0 (personal job search)"


class ManualClient:
    """Generic content-fetch клиент для вручную заведённых вакансий (ats_family
    'manual') — компании без адаптера ни под один из 5 поддерживаемых ATS.
    Не реализует list_jobs/check_job/get_board_name: manual-записи заводятся
    и помечаются verified разовым скриптом в обход штатного discovery/verify."""

    def __init__(self, http_client: httpx.Client | None = None, timeout: float = 15.0,
                 sleep=None):
        self._client = http_client or httpx.Client(timeout=timeout)
        self._sleep = sleep

    def _get(self, url: str) -> httpx.Response:
        kwargs = {} if self._sleep is None else {"sleep": self._sleep}
        return request_with_retry(self._client, "GET", url,
                                  headers={"User-Agent": USER_AGENT}, **kwargs)

    def fetch_content(self, url: str) -> str | None:
        """Сырой HTML страницы (для triage.htmltext.strip_html выше по стеку).
        None — только подтверждённый 404. Сетевые ошибки и прочие статусы
        (5xx/429 после исчерпанных ретраев) пробрасываются исключением — как у
        GreenhouseClient, чтобы triage ретраил, а не хоронил вакансию навсегда."""
        resp = self._get(url)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.text

    def close(self) -> None:
        self._client.close()
