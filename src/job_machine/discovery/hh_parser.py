"""Regex-парсер страницы поиска hh.ru (search/vacancy). Без DOM-библиотеки
(BeautifulSoup/lxml) — как и triage/htmltext.py и telegram_sourcing/parser.py,
этот проект использует regex-only извлечение по стабильным data-qa атрибутам.

Карточка результата (снята live 2026-07-17, см. design doc §2):
  data-qa="vacancy-serp__vacancy"              — контейнер карточки
  data-qa="serp-item__title" href="..."        — ссылка на вакансию
  data-qa="serp-item__title-text"              — заголовок (текст)
  data-qa="vacancy-serp__vacancy-employer-text" — работодатель (текст)
  data-qa="vacancy-serp__vacancy-address"      — локация (текст)
  data-qa="vacancy-label-work-schedule-remote" — присутствует, если remote

Хрупко при смене вёрстки hh.ru — при 0 карточках на HTTP 200 возвращает пустой
список (не исключение); это сигнал для вызывающего кода, не ошибка.
"""

import html as html_module
import re

from job_machine.discovery.models import RawHhJob
from job_machine.triage.htmltext import strip_html

_CARD_RE = re.compile(
    r'data-qa="vacancy-serp__vacancy"(?:(?!data-qa="vacancy-serp__vacancy").)*?'
    r'(?=data-qa="vacancy-serp__vacancy"|\Z)',
    re.DOTALL,
)
_TITLE_LINK_RE = re.compile(
    r'data-qa="serp-item__title"[^>]*href="([^"]+)"', re.DOTALL,
)
_TITLE_TEXT_RE = re.compile(
    r'data-qa="serp-item__title-text"[^>]*>(.*?)</span>', re.DOTALL,
)
_EMPLOYER_RE = re.compile(
    r'data-qa="vacancy-serp__vacancy-employer-text"[^>]*>(.*?)</span>', re.DOTALL,
)
_ADDRESS_RE = re.compile(
    r'data-qa="vacancy-serp__vacancy-address"[^>]*>(.*?)</span>', re.DOTALL,
)
_REMOTE_BADGE_RE = re.compile(r'data-qa="vacancy-label-work-schedule-remote"')


def parse_search_results(html: str) -> list[RawHhJob]:
    """Разобрать страницу результатов поиска hh.ru в список RawHhJob."""
    if not html:
        return []
    out: list[RawHhJob] = []
    for match in _CARD_RE.finditer(html):
        block = match.group(0)
        title_link = _TITLE_LINK_RE.search(block)
        title_text = _TITLE_TEXT_RE.search(block)
        if not title_link or not title_text:
            continue
        employer = _EMPLOYER_RE.search(block)
        address = _ADDRESS_RE.search(block)
        out.append(RawHhJob(
            title=strip_html(title_text.group(1)),
            url=html_module.unescape(title_link.group(1)).strip(),
            company_name=strip_html(employer.group(1)) if employer else None,
            location=strip_html(address.group(1)) if address else None,
            is_remote=bool(_REMOTE_BADGE_RE.search(block)),
        ))
    return out
