import pytest

from job_machine.db import migrate
from job_machine.resume import service


def _apply(conn):
    for m in migrate.pending(migrate.discover_migrations("db/migrations"),
                             migrate.applied_migrations(conn)):
        migrate.apply_migration(conn, m)


def _seed_cloud(conn, candidate_id="andrey-s"):
    from job_machine.cloud.models import (
        CloudAchievement, CloudPosition, CloudSkill, ExperienceCloud,
    )
    from job_machine.cloud.store import upsert_cloud
    upsert_cloud(conn, ExperienceCloud(
        positions=[
            CloudPosition(pid="P-01", company="NSD", title="Head of QA / IT Delivery Leader",
                          start="2024-09", end="present", location="Moscow"),
            CloudPosition(pid="P-05", company="Early", title="Marketer",
                          start="2011-08", end="2013-09", location="Moscow"),  # early career, no bullets
        ],
        achievements=[CloudAchievement(aid="A-04", pid="P-01", text="Throughput delivered",
                                       metric="15,000 test-hours", status="verified")],
        skills=[CloudSkill(name="QA & test strategy", category="skill", framing="Expert")]),
        candidate_id=candidate_id)


def _seed_app(conn, role="Senior QA Engineer", candidate_id="andrey-s"):
    with conn.cursor() as cur:
        cur.execute("insert into vacancy (company, title, canonical_url, vacancy_status, state) "
                    "values ('Acme',%s,'https://acme/apply','triaged','triaged') "
                    "returning vacancy_id", (role,))
        vid = cur.fetchone()[0]
        cur.execute("insert into application (vacancy_id, verdict, package_status, state, "
                    "candidate_id) values (%s,'apply','none','needs_package',%s) "
                    "returning application_id", (vid, candidate_id))
        return str(cur.fetchone()[0])


class _StubPdf:
    def __init__(self):
        self.last_html = None

    def render(self, html):
        self.last_html = html
        return b"%PDF-1.4 stub"

    def close(self):
        pass


@pytest.mark.db
def test_generate_wires_contact_and_summary(tmp_path, db_schema):
    conn, _ = db_schema
    _apply(conn)
    _seed_cloud(conn)
    with conn.cursor() as cur:
        cur.execute("insert into answer (candidate_id, field, value, state) values "
                    "('andrey-s','Email','samojlov.andrey@gmail.com','locked'),"
                    "('andrey-s','Current location','Moscow, Russia','locked') "
                    "on conflict do nothing")
    _seed_app(conn)
    conn.commit()
    pdf = _StubPdf()
    n = service.run_resume(conn, pdf, str(tmp_path), limit=10)
    assert n == 1
    html = pdf.last_html
    # контакт-блок из vault
    assert "samojlov.andrey@gmail.com" in html
    # location из vault не должна утекать в PDF (владелец, 2026-07-16) — см. render.py
    assert "Moscow" not in html
    # Summary-текст с полным тенюром (2011→present, включая early-career позицию без буллетов).
    # Новый дизайн не рендерит явный заголовок «Summary» (см. render.py) — проверяем текст.
    assert "years in technology" in html
    # headline из словаря (роль QA) — роль несёт headline, не Summary
    assert "QA" in html
    # Core strengths подтянуты из skill_groups (та же скорированная под вакансию строка)
    assert "Core strengths: QA &amp; test strategy — Expert" in html


def test_build_jd_summary_from_row_is_deterministic_and_bounded():
    row = {"fit_summary": "Strong QA leadership match.",
           "hard_requirements": [
               {"requirement": "5+ years test automation leadership"},
               {"requirement": "Experience with distributed teams"},
           ]}
    s = service.build_jd_summary(row)
    assert "test automation" in s
    assert "Strong QA leadership match." in s
    assert len(s) <= 600
    # детерминизм
    assert service.build_jd_summary(row) == s


def test_build_jd_summary_empty_row_safe():
    assert service.build_jd_summary({}) == ""
    assert service.build_jd_summary({"fit_summary": "", "hard_requirements": []}) == ""
