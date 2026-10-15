"""Синк hh.ru-вакансий с хорошим fit-скором в company_watchlist. Отдельный шаг
(не авто-хук в триаже) — по образцу scripts/linkedin_watchlist.py, см. дизайн
docs/superpowers/specs/2026-07-17-hh-ru-sourcing-design.md §6."""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from job_machine.watchlist import store
from job_machine.watchlist.models import PostingEvidence

logger = logging.getLogger(__name__)

_GOOD_FIT_BANDS = ("A", "B")


@dataclass
class SyncResult:
    synced: int = 0
    skipped: int = 0


def _candidate_qualifying_vacancies(conn):
    """(vacancy_id, company, title, canonical_url, location) для ats_family='hh'
    с хотя бы одним fit_band в {A,B} у любого кандидата, ещё не синхронизированных."""
    with conn.cursor() as cur:
        cur.execute(
            "select distinct v.vacancy_id, v.company, v.title, v.canonical_url, v.location "
            "from vacancy v "
            "join triage_result t on t.vacancy_id = v.vacancy_id "
            "where v.ats_family = 'hh' and t.fit_band = any(%s) "
            "and not exists (select 1 from hh_watchlist_sync s where s.vacancy_id = v.vacancy_id)",
            (list(_GOOD_FIT_BANDS),),
        )
        return cur.fetchall()


def sync(conn) -> SyncResult:
    """Прогнать одну синхронизацию: qualifying hh-вакансии → upsert_evidence
    + отметка в hh_watchlist_sync. Коммитит per-row — one bad write must not
    roll back prior ones (аналогично scripts/linkedin_watchlist.py)."""
    result = SyncResult()
    rows = _candidate_qualifying_vacancies(conn)
    for vacancy_id, company, title, canonical_url, location in rows:
        if not company:
            result.skipped += 1
            continue
        evidence = PostingEvidence(
            title=title, url=canonical_url, location=location,
            found_at=datetime.now(timezone.utc).isoformat(),
            explicit_global=True,
        )
        try:
            store.upsert_evidence(conn, company, evidence)
            with conn.cursor() as cur:
                cur.execute(
                    "insert into hh_watchlist_sync (vacancy_id) values (%s) "
                    "on conflict (vacancy_id) do nothing",
                    (vacancy_id,),
                )
            conn.commit()  # commit per vacancy — one bad write must not roll back prior ones
        except Exception:
            logger.exception(
                "hh_sync: upsert failed for vacancy_id=%r, company=%r", vacancy_id, company
            )
            conn.rollback()
            continue
        result.synced += 1
    return result
