import httpx

from job_machine.discovery.models import RawSmartRecruitersJob
from job_machine.http.retry import request_with_retry

SMARTRECRUITERS_BASE = "https://api.smartrecruiters.com/v1/companies"

_DESCRIPTION_SECTION_ORDER = (
    "companyDescription", "jobDescription", "qualifications", "additionalInformation",
)


class SmartRecruitersClient:
    """Клиент SmartRecruiters публичного Posting API (без авторизации, документирован,
    проба 2026-07-15). list — offset/limit пагинация по totalFound, без описания;
    detail — GET по id, description собран из jobAd.sections (единого поля нет)."""

    MAX_PAGES = 50  # анти-цикл на аномальный/бесконечный totalFound
    PAGE_SIZE = 100

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
        """Список отдаёт company.name, но пустой борд не гарантирует хотя бы одну
        вакансию — не полагаемся, используем label из sources.json (как Workable/Recruitee)."""
        return None

    def list_jobs(self, token: str) -> list[RawSmartRecruitersJob]:
        url = f"{SMARTRECRUITERS_BASE}/{token}/postings"
        jobs: list[RawSmartRecruitersJob] = []
        offset = 0
        for _ in range(self.MAX_PAGES):
            resp = self._get(url, params={"offset": offset, "limit": self.PAGE_SIZE})
            resp.raise_for_status()
            data = resp.json()
            content = data.get("content", [])
            if not content:
                break
            jobs.extend(RawSmartRecruitersJob.from_api(j) for j in content)
            offset += len(content)
            if offset >= data["totalFound"]:
                break
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
        """None — только подтверждённый 404. Конкатенирует текстовые секции jobAd в
        фиксированном порядке — detail-эндпоинт не отдаёт единое description-поле."""
        resp = self._get(url)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        sections = resp.json().get("jobAd", {}).get("sections", {})
        parts = [sections[key]["text"] for key in _DESCRIPTION_SECTION_ORDER
                 if sections.get(key) and sections[key].get("text")]
        return "\n".join(parts) if parts else None

    def close(self) -> None:
        self._client.close()
