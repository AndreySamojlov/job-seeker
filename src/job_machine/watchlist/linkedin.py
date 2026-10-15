"""Публичный (без логина) поиск вакансий на LinkedIn через python-jobspy —
источник сигналов для вотчлиста компаний (см. дизайн
docs/superpowers/specs/2026-07-03-linkedin-company-watchlist-design.md).

LinkedIn остаётся read-only (CLAUDE.md §3): только чтение вакансий, без логина,
Easy Apply, сообщений, действий с профилем.

ВАЖНО: site_name всегда должен быть ["linkedin"] и не расширяться на другие
сайты jobspy (Indeed/ZipRecruiter/Glassdoor и т.п.). jobspy.linkedin создаёт
сессию с is_tls=False (обычный requests, см. jobspy/linkedin/__init__.py) —
другие сайты в jobspy используют TLS-фингерпринт-спуфинг (tls_client/
TLSRotating) для обхода anti-bot защиты, что нарушало бы non-goal CLAUDE.md §4
("обход rate-limit/anti-bot"). Не добавлять другие сайты в site_name без
повторной проверки, какую сессию они используют внутри jobspy."""

import logging

import pandas as pd
from jobspy import scrape_jobs

from job_machine.watchlist.models import RawSignal, SearchRunResult

logger = logging.getLogger(__name__)

DEFAULT_ROLES = [
    "Software Engineer", "QA Automation Engineer", "DevOps Engineer",
    "Data Engineer", "Data Scientist", "Product Manager", "Program Manager",
    "Project Manager", "Product Designer", "Engineering Manager", "Technical Writer",
]


def search_signals(roles: list[str], results_per_role: int) -> SearchRunResult:
    """Искать remote-вакансии по каждой роли. Ошибка на одной роли не роняет
    прогон — логируется и попадает в failed_roles, остальные роли продолжаются
    (никаких ретраев в цикле — не давим на LinkedIn агрессивным скрейпингом)."""
    signals: list[RawSignal] = []
    failed_roles: list[str] = []
    for role in roles:
        try:
            df = scrape_jobs(
                site_name=["linkedin"],
                search_term=role,
                is_remote=True,
                results_wanted=results_per_role,
                linkedin_fetch_description=True,
            )
        except Exception:
            logger.exception("linkedin_watchlist: search failed for role=%r", role)
            failed_roles.append(role)
            continue
        for _, row in df.iterrows():
            signals.append(_row_to_signal(row))
    return SearchRunResult(signals=signals, failed_roles=failed_roles)


def _clean(value):
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    return value


def _row_to_signal(row) -> RawSignal:
    return RawSignal(
        company=_clean(row.get("company")) or "",
        title=_clean(row.get("title")) or "",
        url=_clean(row.get("job_url")) or "",
        location=_clean(row.get("location")),
        description=_clean(row.get("description")),
        date_posted=(
            str(_clean(row.get("date_posted")))
            if _clean(row.get("date_posted")) is not None else None
        ),
    )
