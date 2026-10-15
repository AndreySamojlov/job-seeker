"""Реальный Chromium-рендер: референсный «худший» кейс должен влезать в 1 страницу A4.

Отдельный файл от test_render.py (тот — чистые HTML-ассерты, без Playwright/I-O).
Маркер browser — как в tests/browser/test_pdf.py.
"""
import asyncio
from io import BytesIO

import pytest
from pypdf import PdfReader

from job_machine.browser.session import SessionManager
from job_machine.resume import render
from job_machine.resume.models import (
    Contact, ResumeSelection, SelectedBullet, SelectedPosition, SkillGroup,
)


def _worst_case_selection() -> ResumeSelection:
    positions = [
        SelectedPosition(
            pid=f"P-{i:02d}", company=f"Company {i}",
            title="Head of QA / IT Delivery Leader",
            start=f"20{11 + i * 3}-01",
            end="present" if i == 3 else f"20{14 + i * 3}-01",
            location="Moscow",
            bullets=[
                SelectedBullet(
                    aid=f"A-{i}-{j}",
                    source_text=(f"Achievement {i}.{j}: led a cross-functional initiative "
                                 "that materially improved delivery throughput and quality "
                                 "across the organization over a sustained period"),
                    source_metric=f"{10 + i + j}x",
                )
                for j in range(4)
            ],
        )
        for i in range(4)
    ]
    return ResumeSelection(
        application_id="worst-case",
        headline="IT Delivery Leader / Program Manager",
        candidate_name="Andrey Samoylov",
        contact=Contact(email="workcockpit@gmail.com", phone="+7 967 241-29-75",
                        location="Moscow, Russia"),
        summary=("13+ years in technology, most recently as IT Delivery Leader / "
                 "Program Manager at Company 3. Core strengths: QA & test strategy "
                 "— Expert (leadership), Quality-org leadership — Expert; led ~100."),
        positions=positions,
        skill_groups=[
            SkillGroup(category="skill", items=[f"Skill {i} — Strong" for i in range(12)]),
            SkillGroup(category="certification",
                      items=[f"Certification {i} — 202{i}" for i in range(4)]),
            SkillGroup(category="education",
                      items=["Lomonosov Moscow State University — Sociology — 2015"]),
            SkillGroup(category="language",
                      items=["English — C1 (Advanced)", "Russian — Native"]),
        ],
    )


@pytest.mark.browser
def test_worst_case_resume_fits_one_page():
    sel = _worst_case_selection()
    verified = {b.aid: b.source_text for p in sel.positions for b in p.bullets}
    html = render.render_html(sel, verified)

    async def _render():
        mgr = SessionManager(headless=True, artifact_dir="artifacts/browser")
        await mgr.start()
        try:
            return await mgr.render_pdf(html)
        finally:
            await mgr.shutdown()

    pdf_bytes = asyncio.run(_render())
    page_count = len(PdfReader(BytesIO(pdf_bytes)).pages)
    assert page_count == 1, f"expected 1 page, got {page_count}"
