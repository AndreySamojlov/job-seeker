"""Харвест бордов для текущих ATS (GH/Lever/Ashby) из открытых сид-датасетов.

Чистые функции (парсинг/фильтры/мёрдж) — здесь и под тестами; сетевые пробы —
в probe_* с троттлингом. Спека: docs/superpowers/specs/2026-07-02-sourcing-expansion-design.md §6.
"""

import re
import time
from urllib.parse import parse_qs, urlparse

import httpx

from job_machine.http.retry import request_with_retry

USER_AGENT = "job-machine-harvest/1.0 (personal job search)"
THROTTLE_SECONDS = 0.4

# Эвристика EU/Cyprus/remote по тексту локации (приоритизация, не жёсткий фильтр).
_EU_HINTS = re.compile(
    r"remote|emea|europe|cyprus|limassol|nicosia|germany|berlin|munich|france|paris|"
    r"netherlands|amsterdam|spain|madrid|barcelona|portugal|lisbon|poland|warsaw|"
    r"krakow|czech|prague|austria|vienna|ireland|dublin|uk\b|united kingdom|london|"
    r"sweden|stockholm|denmark|copenhagen|norway|oslo|finland|helsinki|estonia|"
    r"tallinn|latvia|lithuania|vilnius|greece|athens|italy|milan|rome|belgium|"
    r"brussels|switzerland|zurich|hungary|budapest|romania|bucharest|bulgaria|sofia|"
    r"croatia|zagreb|serbia|belgrade|slovakia|slovenia|malta|luxembourg",
    re.IGNORECASE,
)

_GH_HOSTS = ("boards.greenhouse.io", "boards.eu.greenhouse.io", "job-boards.greenhouse.io",
             "job-boards.eu.greenhouse.io")
_LEVER_HOSTS = ("jobs.lever.co", "jobs.eu.lever.co")
_ASHBY_HOSTS = ("jobs.ashbyhq.com",)
_WORKABLE_HOSTS = ("apply.workable.com",)
_RECRUITEE_HOST_SUFFIX = ".recruitee.com"
_SMARTRECRUITERS_HOSTS = ("jobs.smartrecruiters.com",)
_PINPOINT_HOST_SUFFIX = ".pinpointhq.com"


def extract_ats_token(url: str) -> tuple[str, str] | None:
    """(ats, token) из карьерного URL — поддерживаемые ATS (см. sources.py client_for); иначе None."""
    try:
        p = urlparse(url)
    except ValueError:
        return None
    host = (p.hostname or "").lower()
    first_seg = next((s for s in p.path.split("/") if s), None)
    if host in _GH_HOSTS and first_seg:
        return ("greenhouse", first_seg.lower())
    if host.endswith("greenhouse.io") and p.path.startswith("/embed/job_board"):
        token = parse_qs(p.query).get("for", [None])[0]
        return ("greenhouse", token.lower()) if token else None
    if host in _LEVER_HOSTS and first_seg:
        return ("lever", first_seg.lower())
    if host in _ASHBY_HOSTS and first_seg:
        return ("ashby", first_seg.lower())
    if host in _WORKABLE_HOSTS and first_seg:
        return ("workable", first_seg.lower())
    if host.endswith(_RECRUITEE_HOST_SUFFIX):
        token = host[: -len(_RECRUITEE_HOST_SUFFIX)]
        return ("recruitee", token.lower()) if token else None
    if host in _SMARTRECRUITERS_HOSTS and first_seg:
        return ("smartrecruiters", first_seg.lower())
    if host.endswith(_PINPOINT_HOST_SUFFIX):
        token = host[: -len(_PINPOINT_HOST_SUFFIX)]
        return ("pinpoint", token.lower()) if token else None
    return None


def slug_candidates(name: str) -> list[str]:
    """Кандидаты board-токена из имени компании (для пробы перебором).
    Порядок: слитно, через дефис, первое слово. Без дублей."""
    words = re.findall(r"[a-z0-9]+", name.lower())
    if not words:
        return []
    out = ["".join(words), "-".join(words), words[0]]
    seen: set[str] = set()
    return [s for s in out if not (s in seen or seen.add(s))]


def looks_eu_or_remote(location: str | None) -> bool:
    return bool(location and _EU_HINTS.search(location))


def merge_sources(existing: list[dict], new: list[dict]) -> list[dict]:
    """Новые записи, которых нет в existing по (ats, token)."""
    seen = {(e.get("ats"), e.get("token")) for e in existing}
    out = []
    for entry in new:
        key = (entry.get("ats"), entry.get("token"))
        if key not in seen:
            seen.add(key)
            out.append(entry)
    return out


def _get(client: httpx.Client, url: str, **kw) -> httpx.Response:
    time.sleep(THROTTLE_SECONDS)
    return request_with_retry(client, "GET", url, headers={"User-Agent": USER_AGENT}, **kw)


def _post(client: httpx.Client, url: str, json_body: dict, **kw) -> httpx.Response:
    time.sleep(THROTTLE_SECONDS)
    return request_with_retry(client, "POST", url, json=json_body,
                              headers={"User-Agent": USER_AGENT}, **kw)


# Не переиспользуем GreenhouseClient/LeverClient/AshbyClient: та семантика для
# известных живых бордов (raise_for_status), а тут пробуем неизвестные/вероятно
# мёртвые токены — 404 ожидаем часто, это не ошибка.
def probe_board(client: httpx.Client, ats: str, token: str) -> list[dict] | None:
    """Жив ли борд: список вакансий [{'title','location'}] или None (мёртв/ошибка).
    Только публичные JSON API, без ключей."""
    try:
        if ats == "greenhouse":
            r = _get(client, f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs")
            if r.status_code != 200:
                return None
            return [{"title": j.get("title", ""),
                     "location": (j.get("location") or {}).get("name", "")}
                    for j in r.json().get("jobs", [])]
        if ats == "lever":
            r = _get(client, f"https://api.lever.co/v0/postings/{token}?mode=json")
            if r.status_code == 404:
                # EU data-residency борды (найдено на Quadcode/XM Group/CoinsPaid) живут
                # только на api.eu.lever.co — глобальный хост 404-ит навсегда без этого.
                r = _get(client, f"https://api.eu.lever.co/v0/postings/{token}?mode=json")
            if r.status_code != 200:
                return None
            data = r.json()
            if not isinstance(data, list):
                return None
            return [{"title": j.get("text", ""),
                     "location": (j.get("categories") or {}).get("location", "")}
                    for j in data]
        if ats == "ashby":
            r = _get(client, f"https://api.ashbyhq.com/posting-api/job-board/{token}")
            if r.status_code != 200:
                return None
            return [{"title": j.get("title", ""), "location": j.get("location", "")}
                    for j in r.json().get("jobs", [])]
        if ats == "workable":
            r = _post(client, f"https://apply.workable.com/api/v3/accounts/{token}/jobs", {})
            if r.status_code != 200:
                return None
            out = []
            for j in r.json().get("results", []):
                loc = j.get("location") or {}
                parts = [p for p in (loc.get("city"), loc.get("country")) if p]
                out.append({"title": j.get("title", ""), "location": ", ".join(parts)})
            return out
        if ats == "recruitee":
            r = _get(client, f"https://{token}.recruitee.com/api/offers/")
            if r.status_code != 200:
                return None
            return [{"title": j.get("title", ""), "location": j.get("location") or ""}
                    for j in r.json().get("offers", [])]
        if ats == "smartrecruiters":
            r = _get(client, f"https://api.smartrecruiters.com/v1/companies/{token}/postings",
                      params={"limit": 100})
            if r.status_code != 200:
                return None
            out = []
            for j in r.json().get("content", []):
                loc = j.get("location") or {}
                parts = [p for p in (loc.get("city"), loc.get("country")) if p]
                out.append({"title": j.get("name", ""), "location": ", ".join(parts)})
            return out
        if ats == "pinpoint":
            r = _get(client, f"https://{token}.pinpointhq.com/postings.json")
            if r.status_code != 200:
                return None
            out = []
            for j in r.json().get("data", []):
                loc = j.get("location") or {}
                out.append({"title": j.get("title", ""), "location": loc.get("name") or ""})
            return out
    except (httpx.HTTPError, ValueError):
        # ValueError покрывает json.JSONDecodeError (HTML/cloudflare-challenge/
        # кастомный error-body при статусе 200) — не должно ронять весь CLI-прогон.
        return None
    return None
