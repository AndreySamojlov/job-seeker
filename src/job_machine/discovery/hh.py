"""hh.ru discovery через прямой HTTP (без job-browser/Playwright).

Раньше клиент шёл через job-browser (Playwright) — предположение design doc
docs/superpowers/specs/2026-07-17-hh-ru-sourcing-design.md §2 было в том, что
hh.ru блокирует httpx-клиентов через DDoS-Guard так же, как api.hh.ru/vacancies.
Проверено прямым запросом 2026-07-20: DDoS-Guard стоит только перед JSON API —
страницы search/vacancy и /vacancy/<id> отдаются обычным HTTP GET без анти-бот
стены (реальный HTML с data-qa атрибутами, ни капчи, ни challenge, даже с
дефолтным User-Agent curl). Playwright/job-browser были архитектурной ошибкой:
не нужны и создавали лишнюю нагрузку на и без того перегруженный job-browser
контейнер (см. память lab-do-browser-oom-incident) — отсюда ~50% пустых
прогонов cron'а (см. .hh_discovery_cron.log) из-за флаки браузер-воркера, а не
из-за реальной блокировки источника.
"""

from urllib.parse import quote_plus

import httpx

from job_machine.discovery.hh_parser import parse_search_results
from job_machine.discovery.models import RawHhJob
from job_machine.http.retry import request_with_retry

HH_SEARCH_BASE = "https://hh.ru/search/vacancy"
_NOT_FOUND_MARKERS = ("вакансия удалена", "не найдена", "не найден")


class HhClient:
    """Дискавери-клиент для hh.ru (ats='hh') — прямой httpx, без браузер-воркера."""

    def __init__(self, http_client: httpx.Client | None = None, timeout: float = 15.0):
        self._client = http_client or httpx.Client(timeout=timeout)

    def _get(self, url: str, **kw) -> httpx.Response:
        return request_with_retry(self._client, "GET", url, **kw)

    def get_board_name(self, token: str) -> None:
        return None

    def list_jobs(self, token: str, query: dict | None = None) -> list[RawHhJob]:
        query = query or {}
        text = query.get("text", "")
        area = query.get("area", "1001")
        schedule = query.get("schedule", "remote")
        url = (
            f"{HH_SEARCH_BASE}?text={quote_plus(text)}"
            f"&area={area}&schedule={schedule}&order_by=publication_time"
        )
        resp = self._get(url)
        resp.raise_for_status()
        return parse_search_results(resp.text)

    def check_job(self, url: str) -> str:
        try:
            resp = self._get(url)
        except httpx.HTTPError:
            return "error"
        if resp.status_code >= 400:
            return "error"
        if any(marker in resp.text.lower() for marker in _NOT_FOUND_MARKERS):
            return "gone"
        return "live"

    def fetch_content(self, url: str) -> str | None:
        """HTML вакансии для triage (strip_html выше по стеку). None — если
        страница явно 404/удалена; сетевые ошибки пробрасываются (как у
        остальных клиентов) — triage ретраит, а не хоронит вакансию навсегда."""
        resp = self._get(url)
        resp.raise_for_status()
        if any(marker in resp.text.lower() for marker in _NOT_FOUND_MARKERS):
            return None
        return resp.text

    def close(self) -> None:
        self._client.close()
