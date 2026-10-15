"""Оркестрация генерации резюме. Per-item commit; изоляция падения по заявке.

run_resume — детерминированный floor (verbatim-фразинг, без n8n/LLM).
apply_phrasing — n8n-путь: проверить присланный фразинг → render → PDF → запись.
"""
import os
import re

from job_machine.cloud.store import load_cloud
from job_machine.package.artifacts import hash_file
from job_machine.package.models import ResumeArtifact
from job_machine.resume import honesty, render, selector, store
from job_machine.resume.models import PhrasedBullet, ResumePhrasing
from job_machine.resume.summary import build_summary

_JD_MAX = 600


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s or "resume"


def build_jd_summary(row: dict) -> str:
    """Детерминированная JD-выжимка из pull-строки: fit_summary + топ-requirement-фразы.

    Без нового fetch и без LLM. Обрезается до _JD_MAX символов. Кладётся в
    PhrasingRequest.jd_summary → контекст для контекстного фразинга в n8n RG-12 (§4.1).
    """
    parts: list[str] = []
    fit = (row.get("fit_summary") or "").strip()
    if fit:
        parts.append(fit)
    reqs = []
    for r in row.get("hard_requirements") or []:
        req = (r.get("requirement") or "").strip()
        if req:
            reqs.append(req)
    if reqs:
        parts.append("Key requirements: " + "; ".join(reqs) + ".")
    return " ".join(parts)[:_JD_MAX].strip()


def _generate(conn, pdf_client, base_dir: str, row: dict, phrasing: ResumePhrasing) -> ResumeArtifact:
    cloud = load_cloud(conn, row["candidate_id"])
    sel = selector.build_selection(row["application_id"], row["role"],
                                   row["hard_requirements"], cloud,
                                   candidate_name=row["candidate_name"],
                                   candidate_id=row["candidate_id"])
    sel.contact = store.load_contact(conn, row["candidate_id"])
    sel.summary = build_summary(cloud, sel.headline, sel.skill_groups)
    verified = honesty.verify(sel, phrasing)
    html = render.render_html(sel, verified)
    pdf = pdf_client.render(html)
    out_dir = os.path.join(base_dir, row["candidate_id"], row["application_id"])
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"resume-{_slug(sel.headline)}.pdf")
    with open(path, "wb") as fh:
        fh.write(pdf)
    art = ResumeArtifact(filename=os.path.basename(path), path=os.path.abspath(path),
                         content_hash=hash_file(path))
    aids = [b.aid for p in sel.positions for b in p.bullets]
    store.record_resume(conn, row["application_id"], art, headline=sel.headline, aids=aids)
    return art


def run_resume(conn, pdf_client, base_dir: str, limit: int = 10) -> int:
    """Детерминированный floor: каждая needs-resume заявка → verbatim-фразинг → PDF."""
    built = 0
    for row in store.pull_needs_resume(conn, limit):
        sel = selector.build_selection(row["application_id"], row["role"],
                                       row["hard_requirements"],
                                       load_cloud(conn, row["candidate_id"]),
                                       candidate_name=row["candidate_name"],
                                       candidate_id=row["candidate_id"])
        verbatim = ResumePhrasing(application_id=row["application_id"], bullets=[
            PhrasedBullet(aid=b.aid, phrased_text=b.source_text)
            for p in sel.positions for b in p.bullets])
        try:
            _generate(conn, pdf_client, base_dir, row, verbatim)
            conn.commit()
            built += 1
        except Exception:  # noqa: BLE001 — изоляция падения по заявке
            conn.rollback()
    return built


def apply_phrasing(conn, pdf_client, base_dir: str, phrasing: ResumePhrasing) -> ResumeArtifact | None:
    """n8n-путь: применить присланный (LLM) фразинг. None если заявки нет/уже с résumé."""
    row = store.pull_one_for_resume(conn, phrasing.application_id)
    if row is None:
        return None
    art = _generate(conn, pdf_client, base_dir, row, phrasing)
    conn.commit()
    return art
