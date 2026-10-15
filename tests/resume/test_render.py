from job_machine.resume import render
from job_machine.resume.models import (
    Contact, ResumeSelection, SelectedBullet, SelectedPosition, SkillGroup,
)


def _sel():
    return ResumeSelection(
        application_id="a1", headline="Head of QA / IT Delivery Leader",
        candidate_name="Andrey Samoylov",
        positions=[SelectedPosition(
            pid="P-01", company="NSD", title="Head of QA", start="2024-09",
            end="present", location="Moscow",
            bullets=[SelectedBullet(aid="A-04", source_text="Throughput delivered",
                                    source_metric="15,000 test-hours")])],
        skill_groups=[SkillGroup(category="skill", items=["QA & test strategy — Expert"]),
                      SkillGroup(category="language", items=["English — B2"])])


def test_render_includes_headline_company_bullet_and_skills():
    html = render.render_html(_sel(), {"A-04": "Owned delivery of 15,000 test-hours"})
    assert html.lstrip().startswith("<!doctype html>")
    assert "Head of QA / IT Delivery Leader" in html
    assert "NSD" in html and "2024-09" in html and "present" in html
    assert "Owned delivery of 15,000 test-hours" in html   # uses verified text, not source
    assert "English — B2" in html


def test_render_escapes_html_and_omits_unknown_bullet_gracefully():
    sel = _sel()
    sel.positions[0].bullets[0].source_text = "A & B <script>"
    html = render.render_html(sel, {})   # no verified text for A-04 -> falls back to source
    assert "A &amp; B &lt;script&gt;" in html
    assert "<script>" not in html


def test_render_uses_candidate_name():
    sel = _sel()
    sel.candidate_name = "Ivan Testov"
    html = render.render_html(sel, {})
    assert "<h1>Ivan Testov</h1>" in html
    assert "Andrey Samoylov" not in html


def _mini(**kw):
    base = dict(application_id="a", headline="Head of QA", candidate_name="Andrey S",
                positions=[SelectedPosition(pid="p1", company="Acme", title="Lead",
                    start="2011-01", end="2024-01",
                    bullets=[SelectedBullet(aid="a1", source_text="Led QA org",
                                            source_metric="15")])],
                skill_groups=[])
    base.update(kw)
    return ResumeSelection(**base)


def test_contact_block_rendered_only_present():
    html = render.render_html(_mini(contact=Contact(email="a@b.com", location="Berlin")), {})
    assert "a@b.com" in html
    # Считаем только в <body> — <head> содержит base64-встроенные шрифты, где
    # случайное совпадение с "None" теоретически возможно (см. test_metric_dedup_when_in_text).
    body = html.split("<body>", 1)[1]
    assert "None" not in body    # отсутствующие phone/linkedin не рендерятся


def test_contact_location_never_rendered():
    # 2026-07-16: location в резюме не рендерится вообще (не только RU/Moscow) —
    # владелец решил скрыть геолокацию кандидата из документа целиком.
    html = render.render_html(_mini(contact=Contact(email="a@b.com", location="Berlin")), {})
    body = html.split("<body>", 1)[1]
    assert "Berlin" not in body


def test_position_location_never_rendered():
    sel = _sel()
    assert sel.positions[0].location == "Moscow"
    html = render.render_html(sel, {"A-04": "x"})
    body = html.split("<body>", 1)[1]
    assert "Moscow" not in body


def test_no_contact_no_block():
    html = render.render_html(_mini(contact=None), {})
    assert "mailto" not in html


def test_summary_section():
    # Новый дизайн НЕ рендерит явный заголовок «Summary» (см. хендофф-HTML — после
    # divider сразу идёт <p>, без <h2>Summary</h2>) — проверяем сам текст, а не лейбл.
    html = render.render_html(_mini(summary="13+ years in QA and delivery leadership."), {})
    assert "13+ years in QA and delivery leadership." in html


def test_metric_dash_artifact_stripped():
    sel = _mini(positions=[SelectedPosition(pid="p1", company="Acme", title="Lead",
        bullets=[SelectedBullet(aid="a1", source_text="Owned SLA", source_metric="—")])])
    html = render.render_html(sel, {})
    assert "(—)" not in html


def test_metric_dedup_when_in_text():
    sel = _mini(positions=[SelectedPosition(pid="p1", company="Acme", title="Lead",
        bullets=[SelectedBullet(aid="a1", source_text="Managed 15 engineers",
                                source_metric="15")])])
    html = render.render_html(sel, {})
    # Считаем только в <body> — <head> теперь содержит base64-встроенные шрифты
    # (десятки КБ псевдослучайных символов), которые почти гарантированно содержат
    # подстроку "15" сами по себе и ломают счётчик по всему документу.
    body = html.split("<body>", 1)[1]
    assert body.count("15") == 1   # метрика не дублируется скобкой


def test_metric_not_deduped_on_number_substring():
    # метрика «15» встречается только внутри «2015» → это НЕ дубль, метрика рендерится.
    # "(15)" безопасно искать по всему html — скобки не входят в алфавит base64.
    sel = _mini(positions=[SelectedPosition(pid="p1", company="Acme", title="Lead",
        bullets=[SelectedBullet(aid="a1", source_text="Shipped release in 2015",
                                source_metric="15")])])
    html = render.render_html(sel, {})
    assert "(15)" in html          # граница слова: «15» не поглощено «2015»


def test_position_row_colors_company_name():
    html = render.render_html(_sel(), {"A-04": "x"})
    assert "<span class='co'>NSD</span>" in html


def test_render_includes_embedded_font_faces():
    html = render.render_html(_sel(), {})
    assert "data:font/woff2;base64," in html
    assert "font-family:'Spectral'" in html
    assert "font-family:'Public Sans'" in html
