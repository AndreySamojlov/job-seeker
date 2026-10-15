"""[SAFETY] DB-слой резюме: pull заявок без резюме + запись resume-артефакта.

События несут aids/headline/хеш — НИКОГДА сырой текст буллетов (privacy + token-efficiency).
Секвенсирование с package — через application.resume_artifact_id (без смены state machine).
"""
import uuid

from job_machine import audit
from job_machine.package.models import ResumeArtifact
from job_machine.resume.models import Contact

# answer-vault field → Contact attr. Ключи — реальные из answer-vault (Task 0):
# 'Email', 'Phone', 'Current location'. LinkedIn в vault отсутствует → всегда None
# (§3: отсутствующее не заявляем; ключ оставлен для будущего добавления в vault).
_CONTACT_FIELDS = {"Email": "email", "Phone": "phone",
                   "Current location": "location", "LinkedIn": "linkedin"}

_PULL_COLS = (
    "select a.application_id, a.vacancy_id, v.company, v.title, v.canonical_url, v.ats_family, "
    "(select e.payload_json from event e where e.entity_id = a.application_id "
    " and e.event_type='application.triaged' order by e.created_at desc limit 1), "
    "a.candidate_id, c.name ")


def _row(rec) -> dict:
    aid, vid, company, title, url, ats, triaged, candidate_id, candidate_name = rec
    triaged = triaged or {}
    return {"application_id": str(aid), "vacancy_id": str(vid), "company": company or "",
            "role": title or "", "destination_url": url or "", "ats_family": ats,
            "fit_summary": triaged.get("fit_summary", ""),
            "hard_requirements": triaged.get("hard_requirements", []),
            "candidate_id": candidate_id, "candidate_name": candidate_name or ""}


def pull_needs_resume(conn, limit: int) -> list[dict]:
    """needs_package, без блокера, ещё без résumé. Джойн vacancy + последний triaged event."""
    with conn.cursor() as cur:
        cur.execute(
            _PULL_COLS +
            "from application a join vacancy v on v.vacancy_id = a.vacancy_id "
            "join candidate c on c.candidate_id = a.candidate_id "
            "where a.state='needs_package' and a.current_blocker is null "
            "and a.resume_artifact_id is null order by a.created_at limit %s", (limit,))
        return [_row(r) for r in cur.fetchall()]


def pull_one_for_resume(conn, application_id: str) -> dict | None:
    """Одна заявка для /resume/apply (должна быть ещё без résumé — идемпотентность)."""
    with conn.cursor() as cur:
        cur.execute(
            _PULL_COLS +
            "from application a join vacancy v on v.vacancy_id = a.vacancy_id "
            "join candidate c on c.candidate_id = a.candidate_id "
            "where a.application_id=%s and a.resume_artifact_id is null",
            (uuid.UUID(application_id),))
        rec = cur.fetchone()
    return _row(rec) if rec else None


def load_contact(conn, candidate_id: str) -> Contact:
    """Contact из answer-vault по реальным ключам; отсутствующее поле → None (§3)."""
    with conn.cursor() as cur:
        cur.execute("select field, value from answer where candidate_id=%s "
                    "and field = any(%s)",
                    (candidate_id, list(_CONTACT_FIELDS.keys())))
        got = {f: v for f, v in cur.fetchall() if v}
    return Contact(**{attr: got.get(field) for field, attr in _CONTACT_FIELDS.items()})


def record_resume(conn, application_id: str, art: ResumeArtifact, headline: str,
                  aids: list[str]) -> None:
    aid = uuid.UUID(application_id)
    with conn.cursor() as cur:
        cur.execute(
            "insert into artifact (application_id, artifact_type, path_or_uri, content_hash) "
            "values (%s,'resume',%s,%s) returning artifact_id",
            (aid, art.path, art.content_hash))
        rid = cur.fetchone()[0]
        cur.execute("update application set resume_artifact_id=%s, updated_at=now() "
                    "where application_id=%s", (rid, aid))
    audit.emit_event(conn, "application", aid, "application.resume_ready", {
        "headline": headline, "aids": aids,
        "resume": {"filename": art.filename, "content_hash": art.content_hash}})
