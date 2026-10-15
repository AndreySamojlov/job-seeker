"""Глобальный вотчлист компаний (см. дизайн
docs/superpowers/specs/2026-07-03-linkedin-company-watchlist-design.md)."""

import json

from job_machine.discovery.normalize import normalize_text
from job_machine.watchlist.models import PostingEvidence

_SAMPLE_CAP = 5


def upsert_evidence(conn, company: str, evidence: PostingEvidence) -> bool:
    """Insert новую компанию или инкрементнуть существующую (дедуп по
    normalize_text(company)). Возвращает True при вставке новой строки, False
    при инкременте существующей или no-op на пустой company.

    Select-then-write, не atomic — приемлемо для ручного низкочастотного
    CLI-скрипта (не конкурентный путь)."""
    normalized = normalize_text(company)
    if normalized is None:
        return False
    entry = {
        "title": evidence.title,
        "url": evidence.url,
        "location": evidence.location,
        "found_at": evidence.found_at,
        "explicit_global": evidence.explicit_global,
    }
    with conn.cursor() as cur:
        cur.execute(
            "select sample_postings from company_watchlist "
            "where company_name_normalized = %s",
            (normalized,),
        )
        row = cur.fetchone()
        if row is None:
            cur.execute(
                "insert into company_watchlist "
                "(company_name, company_name_normalized, sample_postings) "
                "values (%s, %s, %s::jsonb)",
                (company, normalized, json.dumps([entry])),
            )
            return True
        postings = list(row[0]) + [entry]
        postings = postings[-_SAMPLE_CAP:]
        cur.execute(
            "update company_watchlist set "
            "  evidence_count = evidence_count + 1, "
            "  last_seen_at = now(), "
            "  sample_postings = %s::jsonb "
            "where company_name_normalized = %s",
            (json.dumps(postings), normalized),
        )
        return False
