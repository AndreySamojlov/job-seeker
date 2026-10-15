import httpx

from job_machine.discovery.models import RawAshbyJob
from job_machine.http.retry import request_with_retry

ASHBY_BASE = "https://api.ashbyhq.com/posting-api/job-board"


class AshbyClient:
    """Клиент Ashby публичного Job Board API (без авторизации)."""

    def __init__(
        self,
        http_client: httpx.Client | None = None,
        base_url: str = ASHBY_BASE,
        timeout: float = 15.0,
        sleep=None,
    ):
        self._client = http_client or httpx.Client(timeout=timeout)
        self._base = base_url.rstrip("/")
        self._sleep = sleep
        self._board_cache: dict[str, dict | None] = {}

    def _get(self, url: str, **params_kwargs) -> httpx.Response:
        kwargs = dict(params_kwargs)
        if self._sleep is not None:
            kwargs["sleep"] = self._sleep
        return request_with_retry(self._client, "GET", url, **kwargs)

    def _board(self, token: str) -> dict | None:
        """Получить данные доски: 200→dict, 404→None, иначе raise_for_status.
        Кэшируется на инстанс (по token) — check_job/fetch_content рефетчают доску
        на КАЖДУЮ вакансию (нет per-job endpoint, см. check_job), без кэша batch-
        верификация N вакансий с одной доски дала бы N полных GET одной доски.
        Транзиентная ошибка (raise) в кэш не попадает — следующий вызов реально
        сходит в сеть."""
        if token in self._board_cache:
            return self._board_cache[token]
        resp = self._get(
            f"{self._base}/{token}",
            params={"includeCompensation": "true"},
        )
        if resp.status_code == 404:
            data = None
        else:
            resp.raise_for_status()
            data = resp.json()
        self._board_cache[token] = data
        return data

    def get_board_name(self, token: str) -> str | None:
        data = self._board(token)
        if data is None:
            return None
        return data.get("name")

    def list_jobs(self, token: str) -> list[RawAshbyJob]:
        data = self._board(token)
        if data is None:
            return []
        return [RawAshbyJob.from_api(j) for j in data.get("jobs", [])]

    def _parse_job_url(self, url: str) -> tuple[str, str] | None:
        """Разобрать source_url вида {base}/{token}/{job_id} на (token, job_id).
        None, если url не соответствует публичному posting-api Ashby."""
        prefix = f"{self._base}/"
        if not url.startswith(prefix):
            return None
        token, sep, job_id = url[len(prefix):].partition("/")
        if not sep or not token or not job_id or "/" in job_id:
            return None
        return token, job_id

    def _find_job(self, token: str, job_id: str) -> dict | None:
        """Найти job_id в board-level листинге (кэшированном через _board).
        Ashby публичный posting-api НЕ имеет per-job GET-эндпоинта (подтверждено:
        всегда 401, даже без валидного job id) — единственный публичный источник
        истины — тот же листинг, что используют list_jobs/get_board_name."""
        data = self._board(token)
        if data is None:
            return None
        for job in data.get("jobs", []):
            if job.get("id") == job_id:
                return job
        return None

    def check_job(self, url: str) -> str:
        """Проверить вакансию: 'live' (id найден в листинге доски) / 'gone' (доска 404
        или id отсутствует — вакансия делистнута) / 'error' (прочее/сеть)."""
        parsed = self._parse_job_url(url)
        if parsed is None:
            return "error"
        token, job_id = parsed
        try:
            job = self._find_job(token, job_id)
        except httpx.HTTPError:
            return "error"
        return "live" if job is not None else "gone"

    def fetch_content(self, url: str) -> str | None:
        """Получить контент вакансии (поле descriptionHtml/descriptionPlain).
        None — доска 404 или id отсутствует в листинге (вакансия делистнута).
        Сетевые ошибки и прочие статусы пробрасываются исключением — вызывающий код
        (triage) должен ретраить позже, а не считать вакансию мёртвой."""
        parsed = self._parse_job_url(url)
        if parsed is None:
            raise ValueError(f"malformed Ashby source_url: {url}")
        token, job_id = parsed
        job = self._find_job(token, job_id)
        if job is None:
            return None
        return job.get("descriptionHtml") or job.get("descriptionPlain")

    def close(self) -> None:
        self._client.close()
