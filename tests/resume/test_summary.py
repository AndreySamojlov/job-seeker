from job_machine.cloud.models import CloudPosition, ExperienceCloud
from job_machine.resume.models import SkillGroup
from job_machine.resume.summary import build_summary


def test_full_tenure_from_all_positions():
    cloud = ExperienceCloud(positions=[
        CloudPosition(pid="p1", company="A", title="X", start="2011-03", end="2016-01"),
        CloudPosition(pid="p2", company="B", title="Y", start="2016-02", end="2024-06"),
    ], achievements=[], skills=[])
    s = build_summary(cloud, "Head of QA / Delivery Leader")
    assert "13+" in s or "13 " in s     # 2011→2024 ≈ 13 лет
    # §3-честность: Summary заявляет общий стаж, НЕ приписывая все годы лидерству/роли
    assert "leadership" not in s.lower()
    assert "years in technology" in s


def test_uses_all_positions_not_only_those_with_bullets():
    # позиция без буллетов (early career) всё равно расширяет тенюр
    cloud = ExperienceCloud(positions=[
        CloudPosition(pid="p1", company="A", title="X", start="2013-01", end="2014-07"),
        CloudPosition(pid="p2", company="B", title="Y", start="2015-09", end="2024-01"),
    ], achievements=[], skills=[])
    s = build_summary(cloud, "H")
    assert "11+" in s or "11 " in s     # 2013→2024 ≈ 11 лет (взято min(start) по всем)


def test_present_end_counts_toward_span():
    cloud = ExperienceCloud(positions=[
        CloudPosition(pid="p1", company="A", title="X", start="2011-01", end="present"),
    ], achievements=[], skills=[])
    s = build_summary(cloud, "H")
    assert isinstance(s, str) and s     # 'present' не ломает и даёт непустую строку


def test_empty_cloud_safe():
    s = build_summary(ExperienceCloud(positions=[], achievements=[], skills=[]), "H")
    assert isinstance(s, str)


def test_mentions_headline_and_most_recent_company():
    cloud = ExperienceCloud(positions=[
        CloudPosition(pid="p1", company="Early Co", title="X", start="2011-03", end="2016-01"),
        CloudPosition(pid="p2", company="NSD", title="Y", start="2016-02", end="2024-06"),
    ], achievements=[], skills=[])
    s = build_summary(cloud, "IT Delivery Leader / Program Manager")
    assert "most recently as IT Delivery Leader / Program Manager at NSD" in s
    assert "Early Co" not in s   # самая старая компания в резюме-summary не фигурирует


def test_core_strengths_from_top_skill_group_items():
    cloud = ExperienceCloud(positions=[
        CloudPosition(pid="p1", company="NSD", title="X", start="2016-02", end="2024-06"),
    ], achievements=[], skills=[])
    groups = [
        SkillGroup(category="skill", items=["QA & test strategy — Expert", "Quality-org leadership — Expert"]),
        SkillGroup(category="certification", items=["ISTQB Foundation Level — 2023"]),
    ]
    s = build_summary(cloud, "H", groups)
    assert "Core strengths: QA & test strategy — Expert, Quality-org leadership — Expert." in s
    assert "ISTQB" not in s   # certification-категория не попадает в Core strengths


def test_no_skill_groups_omits_core_strengths_clause():
    cloud = ExperienceCloud(positions=[
        CloudPosition(pid="p1", company="NSD", title="X", start="2016-02", end="2024-06"),
    ], achievements=[], skills=[])
    s = build_summary(cloud, "H")
    assert "Core strengths" not in s


def test_core_strengths_skips_weak_framing_items():
    cloud = ExperienceCloud(positions=[
        CloudPosition(pid="p1", company="NSD", title="X", start="2016-02", end="2024-06"),
    ], achievements=[], skills=[])
    groups = [
        SkillGroup(category="skill", items=[
            "Python — Fundamentals only",
            "QA & test strategy — Expert",
            "Quality-org leadership — Expert",
        ]),
    ]
    s = build_summary(cloud, "H", groups)
    assert "Core strengths: QA & test strategy — Expert, Quality-org leadership — Expert." in s
    assert "Fundamentals only" not in s


def test_core_strengths_omitted_when_all_items_weak():
    cloud = ExperienceCloud(positions=[
        CloudPosition(pid="p1", company="NSD", title="X", start="2016-02", end="2024-06"),
    ], achievements=[], skills=[])
    groups = [
        SkillGroup(category="skill", items=[
            "Python — Fundamentals only",
            "Selenium / PyTest / Kafka / Docker — Project-context familiarity (team tools)",
        ]),
    ]
    s = build_summary(cloud, "IT Delivery Leader / Program Manager", groups)
    assert "Core strengths" not in s
    # остальной Summary всё равно рендерится (стаж/headline/company не зависят от skill-фильтра)
    assert "most recently as IT Delivery Leader / Program Manager at NSD" in s


def test_core_strengths_from_nonstandard_category():
    # daria-b-кейс: единственная skill-подобная категория называется "qa", не "skill".
    # Раньше build_summary искал буквально category=="skill" и Core strengths не
    # появлялся вообще (баг 2).
    cloud = ExperienceCloud(positions=[
        CloudPosition(pid="p1", company="Innotech", title="Senior Test Engineer",
                     start="2022-10", end="present"),
    ], achievements=[], skills=[])
    groups = [
        SkillGroup(category="qa", items=["Manual testing — Core manual QA",
                                         "REST API testing — Postman"]),
        SkillGroup(category="language", items=["English — B2"]),
    ]
    s = build_summary(cloud, "Senior Test Engineer", groups)
    assert "Core strengths: Manual testing — Core manual QA, REST API testing — Postman." in s
    assert "English" not in s.split("Core strengths")[-1]   # language не попадает в Core strengths


def test_core_strengths_unions_multiple_skill_like_categories_in_order():
    cloud = ExperienceCloud(positions=[
        CloudPosition(pid="p1", company="X", title="Y", start="2020-01", end="present"),
    ], achievements=[], skills=[])
    groups = [
        SkillGroup(category="qa", items=["Manual testing — Core"]),
        SkillGroup(category="data", items=["SQL — DB validation"]),
    ]
    s = build_summary(cloud, "H", groups)
    # top-2 берутся по порядку уже посчитанных groups (qa первая, data вторая)
    assert "Core strengths: Manual testing — Core, SQL — DB validation." in s
