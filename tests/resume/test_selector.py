from job_machine.cloud.models import (
    CloudAchievement, CloudPosition, CloudSkill, ExperienceCloud,
)
from job_machine.resume import selector


def _cloud():
    return ExperienceCloud(
        positions=[
            CloudPosition(pid="P-01", company="NSD", title="Head of QA / IT Delivery Leader",
                          start="2024-09", end="present", location="Moscow"),
            CloudPosition(pid="P-02", company="Innotech", title="IT Delivery Leader / QA Lead",
                          start="2021-03", end="2024-09", location="Moscow"),
            CloudPosition(pid="P-06", company="CSCP", title="Sociologist",
                          start="2013-01", end="2014-07", location="Moscow"),  # no achievements
        ],
        achievements=[
            CloudAchievement(aid="A-03", pid="P-01", text="Introduced Scrum, improving delivery",
                             metric="2.5x", status="verified", claims="C-007"),
            CloudAchievement(aid="A-04", pid="P-01", text="Project throughput under management",
                             metric="15,000 test-hours; 1,600 defects", status="verified"),
            CloudAchievement(aid="A-06", pid="P-02", text="Built systemic quality control and automation",
                             metric="100% regression", status="verified", claims="C-011"),
            CloudAchievement(aid="A-99", pid="P-02", text="—", metric="—", status="",
                             claims=""),  # артефакт: пустой текст
        ],
        skills=[
            CloudSkill(name="QA & test strategy", category="skill", framing="Expert"),
            CloudSkill(name="Automation strategy", category="skill", framing="Strong"),
            CloudSkill(name="ISTQB CTAL Test Manager", category="certification", framing="2023"),
            CloudSkill(name="English", category="language", framing="B2 (self-assessment)"),
        ])


def test_selects_only_positions_with_achievements_recent_first():
    sel = selector.build_selection("a1", "QA Lead", [], _cloud())
    pids = [p.pid for p in sel.positions]
    assert pids == ["P-01", "P-02"]          # P-06 dropped (no achievements), recent first


def test_requirement_overlap_orders_bullets_within_position():
    reqs = [{"requirement": "test automation regression coverage",
             "evidence_claim_ids": ["C-011"]}]
    sel = selector.build_selection("a1", "QA Lead", reqs, _cloud())
    p02 = next(p for p in sel.positions if p.pid == "P-02")
    assert p02.bullets[0].aid == "A-06"      # automation/regression scores highest


def test_headline_uses_role_map_qa_and_delivery():
    # headline-словарь имеет приоритет над fallback-перестановкой (§4.2) —
    # ТОЛЬКО если у candidate_id есть записи в конфиге.
    from job_machine.resume.headline import headline_for_role
    sel_del = selector.build_selection("a1", "IT Delivery Manager", [], _cloud(),
                                       candidate_id="andrey-s")
    assert sel_del.headline == headline_for_role("andrey-s", "IT Delivery Manager", fallback="")
    assert "Delivery" in sel_del.headline
    sel_qa = selector.build_selection("a1", "Senior QA Engineer", [], _cloud(),
                                      candidate_id="andrey-s")
    assert sel_qa.headline == headline_for_role("andrey-s", "Senior QA Engineer", fallback="")
    assert "QA" in sel_qa.headline


def test_headline_falls_back_to_choose_when_no_map_match():
    # роль без ключевого слова словаря → fallback _choose_headline (половинки title)
    sel = selector.build_selection("a1", "Ninja Guru", [], _cloud(), candidate_id="andrey-s")
    assert sel.headline == "Head of QA / IT Delivery Leader"   # positions[0].title as-is


def test_headline_no_canned_override_without_candidate_config():
    # Кандидат без записей в конфиге (default candidate_id="") — роль дословно
    # совпадает с ключевыми словами andrey-s ("qa"), но канная фраза НЕ подставляется:
    # это regression-тест на баг 1 (утечка чужого заголовка).
    sel = selector.build_selection("a1", "Senior QA Engineer", [], _cloud())
    assert sel.headline == "Head of QA / IT Delivery Leader"    # честный fallback, не канная фраза
    assert sel.headline != "Head of QA / Quality Engineering Leader"


def test_artifact_bullet_dropped():
    sel = selector.build_selection("a1", "QA Lead", [], _cloud())
    aids = {b.aid for p in sel.positions for b in p.bullets}
    assert "A-99" not in aids     # пустой/«—» текст отсеян
    assert "A-06" in aids


def test_jd_summary_field_is_string_from_selector():
    hr = [{"requirement": "5+ years test automation", "evidence_claim_ids": []}]
    sel = selector.build_selection("a1", "QA Lead", hr, _cloud())
    req = selector.phrasing_request(sel)
    # selector держит jd_summary пустым — наполняет service (Task 6); контракт = строка
    assert isinstance(req.jd_summary, str)


def test_skill_groups_ordered_and_verbatim():
    sel = selector.build_selection("a1", "QA Lead", [], _cloud())
    cats = [g.category for g in sel.skill_groups]
    assert cats == ["skill", "certification", "language"]      # fixed order, empty groups dropped
    assert "ISTQB CTAL Test Manager — 2023" in sel.skill_groups[1].items


def test_skill_framing_dash_not_rendered():
    cloud = ExperienceCloud(
        positions=[CloudPosition(pid="P-01", company="NSD", title="Head of QA",
                                 start="2024-09", end="present")],
        achievements=[CloudAchievement(aid="A-1", pid="P-01", text="Did X", metric="",
                                       status="verified")],
        skills=[CloudSkill(name="Selenium", category="skill", framing="—"),
                CloudSkill(name="Kafka", category="skill", framing="")])
    sel = selector.build_selection("a1", "QA", [], cloud)
    skill_items = [i for g in sel.skill_groups for i in g.items]
    assert "Selenium" in skill_items and "Kafka" in skill_items   # framing «—»/пусто → только name
    assert not any("—" in i for i in skill_items)


def test_phrasing_request_lists_all_bullets():
    sel = selector.build_selection("a1", "QA Lead", [], _cloud())
    req = selector.phrasing_request(sel)
    aids = {b["aid"] for b in req.bullets}
    assert aids == {"A-03", "A-04", "A-06"}
    assert req.headline == sel.headline


def test_build_selection_passes_through_candidate_name():
    sel = selector.build_selection("a1", "QA Lead", [], _cloud(), candidate_name="X")
    assert sel.candidate_name == "X"


def test_nonstandard_skill_category_scored_and_kept():
    # daria-b-подобный кейс: категория "qa" (не "skill") должна получить тот же
    # req_terms-скоринг/усечение, что раньше было только у "skill", а не молча
    # выпасть из resume (баг 2).
    cloud = ExperienceCloud(
        positions=[CloudPosition(pid="P-01", company="Innotech", title="Senior Test Engineer",
                                 start="2022-10", end="present")],
        achievements=[CloudAchievement(aid="A-1", pid="P-01", text="Did X", metric="",
                                       status="verified")],
        skills=[CloudSkill(name="Manual testing", category="qa", framing="Core manual QA"),
                CloudSkill(name="SQL", category="data", framing="DB validation"),
                CloudSkill(name="English", category="language", framing="B2")])
    sel = selector.build_selection("a1", "QA Automation Engineer", [], cloud)
    cats = [g.category for g in sel.skill_groups]
    assert "qa" in cats and "data" in cats           # ничего не потеряно
    qa_group = next(g for g in sel.skill_groups if g.category == "qa")
    assert "Manual testing — Core manual QA" in qa_group.items


def test_skill_like_categories_ordered_by_req_term_relevance():
    # Категория с большим пересечением по req_terms должна идти раньше в skill_groups.
    cloud = ExperienceCloud(
        positions=[CloudPosition(pid="P-01", company="X", title="Y",
                                 start="2020-01", end="present")],
        achievements=[CloudAchievement(aid="A-1", pid="P-01", text="Did X", metric="",
                                       status="verified")],
        skills=[CloudSkill(name="Release management", category="process", framing=""),
                CloudSkill(name="Kafka event validation", category="qa", framing="")])
    reqs = [{"requirement": "Kafka event validation testing", "evidence_claim_ids": []}]
    sel = selector.build_selection("a1", "QA Engineer", reqs, cloud)
    cats = [g.category for g in sel.skill_groups]
    assert cats.index("qa") < cats.index("process")   # qa совпадает с req_terms сильнее


def test_reserved_categories_stay_fixed_order_after_skill_like():
    cloud = ExperienceCloud(
        positions=[CloudPosition(pid="P-01", company="X", title="Y",
                                 start="2020-01", end="present")],
        achievements=[CloudAchievement(aid="A-1", pid="P-01", text="Did X", metric="",
                                       status="verified")],
        skills=[CloudSkill(name="English", category="language", framing=""),
                CloudSkill(name="ISTQB", category="certification", framing=""),
                CloudSkill(name="Manual testing", category="qa", framing="")])
    sel = selector.build_selection("a1", "QA", [], cloud)
    cats = [g.category for g in sel.skill_groups]
    assert cats == ["qa", "certification", "language"]   # skill-подобная первой, reserved — фикс. порядок
