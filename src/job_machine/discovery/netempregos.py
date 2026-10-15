import xml.etree.ElementTree as ET

import httpx

from job_machine.discovery.models import RawNetEmpregosJob
from job_machine.discovery.rss import parse_rss_items
from job_machine.http.retry import request_with_retry

NET_EMPREGOS_RSS_URL = "https://www.net-empregos.com/rssfeed.asp"

# WAF net-empregos.com сбрасывает TLS-соединение (RST) для запросов с дефолтным
# User-Agent httpx/curl — воспроизведено на lab-do 2026-07-20 (curl без -A: RST
# за ~0.2с; curl -A "curl/8.5.0": тот же RST; honest self-identifying UA, как у
# harvest.py/manual.py, и даже голый python-httpx/x.x — проходят 200). Похоже на
# точечное правило "блокировать curl", не полноценный anti-bot — честного UA
# достаточно, маскировка под браузер не нужна.
NET_EMPREGOS_USER_AGENT = "job-machine-netempregos/1.0 (personal job search)"

# 200 с телом не-RSS (WAF-заглушка/maintenance-страница вместо фида) не кидает
# httpx.HTTPError — ET.fromstring внутри parse_rss_items падает своим
# xml.etree.ElementTree.ParseError. Без него в кэше-неудач ниже такой ответ
# ронял бы весь батч run_verify тем же способом, что и сетевой сбой (см.
# _ensure_cache).
_FETCH_ERRORS: tuple[type[Exception], ...] = (httpx.HTTPError, ET.ParseError)


class NetEmpregosClient:
    """Клиент RSS-фида Net-Empregos.com (Португалия, публичный, без ключа,
    TTL 5 мин — часто обновляется). Company — из dc:creator, location — regex
    из description (см. RawNetEmpregosJob.from_feed_item)."""

    def __init__(self, http_client: httpx.Client | None = None, timeout: float = 15.0):
        self._client = http_client or httpx.Client(timeout=timeout)
        self._cache: list[RawNetEmpregosJob] | None = None
        self._fetch_error: Exception | None = None

    def _get(self, url: str, **kw) -> httpx.Response:
        return request_with_retry(
            self._client, "GET", url, headers={"User-Agent": NET_EMPREGOS_USER_AGENT}, **kw
        )

    def get_board_name(self, token: str) -> None:
        return None

    def list_jobs(self, token: str, query: dict | None = None) -> list[RawNetEmpregosJob]:
        resp = self._get(NET_EMPREGOS_RSS_URL)
        resp.raise_for_status()
        return [RawNetEmpregosJob.from_feed_item(f) for f in parse_rss_items(resp.text)]

    def _ensure_cache(self) -> list[RawNetEmpregosJob]:
        """Кэшируем и успех, и неудачу фида: без этого один сбой (сеть/WAF) при
        первой netempregos-вакансии в батче run_verify заново гонял бы
        list_jobs() (3 попытки request_with_retry) на КАЖДУЮ следующую вакансию
        того же батча — один сбой раздувался в сотни сетевых попыток и выносил
        весь вызов за внешний таймаут без единого коммита (см. service.run_verify:
        один ats-клиент переиспользуется на весь батч одного ats_family)."""
        if self._cache is None:
            if self._fetch_error is not None:
                raise self._fetch_error
            try:
                self._cache = self.list_jobs("")
            except _FETCH_ERRORS as exc:
                self._fetch_error = exc
                raise
        return self._cache

    def check_job(self, url: str) -> str:
        try:
            jobs = self._ensure_cache()
        except _FETCH_ERRORS:
            return "error"
        return "live" if any(j.link == url for j in jobs) else "gone"

    def fetch_content(self, url: str) -> str | None:
        for j in self._ensure_cache():
            if j.link == url:
                return j.description
        return None

    def close(self) -> None:
        self._client.close()
