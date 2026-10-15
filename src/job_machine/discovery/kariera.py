import json
import re
import time
import xml.etree.ElementTree as ET

import httpx

from job_machine.discovery.models import RawKarieraJob
from job_machine.http.retry import request_with_retry

SITEMAP_INDEX_URL = "https://www.kariera.gr/sitemap.xml"
_SITEMAP_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
_JSONLD_RE = re.compile(
    r'<script type="application/ld\+json">(.*?)</script>', re.DOTALL,
)


class KarieraClient:
    """Двухфазный клиент: sitemap.xml → job-URL из jobs-details сабсайтмапов →
    per-URL GET + извлечение JSON-LD JobPosting (Kariera.gr не отдаёт JSON API,
    но каждая вакансия несёт schema.org-разметку — спека §3). Bounded-батч —
    MAX_JOBS_PER_RUN, не весь sitemap за один проход."""

    MAX_JOBS_PER_RUN = 200
    PAGE_SLEEP_SECONDS = 1.0

    def __init__(self, http_client: httpx.Client | None = None,
                 timeout: float = 15.0, sleep=None):
        self._client = http_client or httpx.Client(timeout=timeout, follow_redirects=True)
        self._sleep = sleep or time.sleep

    def _get(self, url: str) -> httpx.Response:
        return request_with_retry(
            self._client, "GET", url, headers={"User-Agent": "Mozilla/5.0"},
        )

    def get_board_name(self, token: str) -> None:
        return None

    def _job_urls(self) -> list[str]:
        resp = self._get(SITEMAP_INDEX_URL)
        resp.raise_for_status()
        index = ET.fromstring(resp.text)
        sub_sitemaps = [
            loc.text for loc in index.findall(".//sm:sitemap/sm:loc", _SITEMAP_NS)
            if loc.text and "jobs-details" in loc.text
        ]
        urls: list[str] = []
        for sm_url in sub_sitemaps:
            resp = self._get(sm_url)
            resp.raise_for_status()
            sub = ET.fromstring(resp.text)
            urls.extend(
                loc.text for loc in sub.findall(".//sm:url/sm:loc", _SITEMAP_NS) if loc.text
            )
            if len(urls) >= self.MAX_JOBS_PER_RUN:
                break
        return urls[: self.MAX_JOBS_PER_RUN]

    @staticmethod
    def _extract_jsonld(html: str) -> dict | None:
        for raw_block in _JSONLD_RE.findall(html):
            try:
                data = json.loads(raw_block)
            except json.JSONDecodeError:
                continue
            if data.get("@type") == "JobPosting":
                return data
        return None

    def list_jobs(self, token: str, query: dict | None = None) -> list[RawKarieraJob]:
        jobs: list[RawKarieraJob] = []
        for url in self._job_urls():
            resp = self._get(url)
            if resp.status_code != 200:
                continue
            data = self._extract_jsonld(resp.text)
            if data is not None:
                jobs.append(RawKarieraJob.from_jsonld(data, url))
            self._sleep(self.PAGE_SLEEP_SECONDS)
        return jobs

    def check_job(self, url: str) -> str:
        try:
            resp = self._get(url)
        except httpx.HTTPError:
            return "error"
        if resp.status_code == 404:
            return "gone"
        if resp.status_code != 200:
            return "error"
        return "live" if self._extract_jsonld(resp.text) is not None else "gone"

    def fetch_content(self, url: str) -> str | None:
        resp = self._get(url)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        data = self._extract_jsonld(resp.text)
        return data.get("description") if data else None

    def close(self) -> None:
        self._client.close()
