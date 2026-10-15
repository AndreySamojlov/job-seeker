from job_machine.triage.gates import CandidateProfile
from job_machine.triage.gates_config import load_gate_config
from job_machine.triage.models import TriageVerdict
from job_machine.triage.score_config import load_score_config
from job_machine.triage.scoring import (
    _domain_vector, _geo_mode_vector, _hands_on_vector, _requirements_vector,
    _role_family_vector, _seniority_vector, _stack_vector)

CFG = load_score_config()
GATES = load_gate_config()


def _v(**kw):
    base = dict(vacancy_id="v1", verdict="apply", fit_summary="x",
                hard_requirements=[])
    base.update(kw)
    return TriageVerdict(**base)


def _p(**kw):
    base = dict(roles=["QA"], locations=["Europe"], seniority_band="lead",
                company_daily_cap=5)
    base.update(kw)
    return CandidateProfile(**base)


def test_requirements_all_strong_must():
    v = _v(hard_requirements=[{"requirement": "a", "status": "strong"},
                              {"requirement": "b", "status": "strong"}])
    score, conf = _requirements_vector(v, CFG)
    assert score == 100 and conf == 1.0


def test_requirements_nice_gap_weighs_half_of_must_gap():
    # must:strong(1.0×100) + nice:gap(0.5×0) → 100/1.5 = 67
    v = _v(hard_requirements=[{"requirement": "a", "status": "strong"},
                              {"requirement": "b", "status": "gap",
                               "importance": "nice"}])
    assert _requirements_vector(v, CFG)[0] == 67
    # оба must → 100/2 = 50: то же соотношение статусов, но провал по обязательному
    v2 = _v(hard_requirements=[{"requirement": "a", "status": "strong"},
                               {"requirement": "b", "status": "gap"}])
    assert _requirements_vector(v2, CFG)[0] == 50


def test_empty_requirements_scores_zero_not_excluded():
    # Регресс на 118 живых строк: apply с пустым списком требований больше не
    # получает высокий балл за счёт выпадения оси из знаменателя.
    score, conf = _requirements_vector(_v(), CFG)
    assert score == 0


def test_unknown_status_lowers_confidence():
    v = _v(hard_requirements=[{"requirement": "a", "status": "strong"},
                              {"requirement": "b", "status": "unknown"}])
    score, conf = _requirements_vector(v, CFG)
    assert score == 50 and conf == 0.5


def test_hands_on_exact_match_is_full():
    v = _v(hands_on={"required_level": "light"})
    assert _hands_on_vector(v, _p(hands_on_band="light"), CFG) == 100


def test_hands_on_overshoot_is_not_penalised():
    # Кандидат глубже, чем требует роль — это не гэп (решение владельца 2026-08-15).
    v = _v(hands_on={"required_level": "light"})
    assert _hands_on_vector(v, _p(hands_on_band="deep"), CFG) == 100


def test_hands_on_undershoot_scales_by_distance():
    v = _v(hands_on={"required_level": "deep"})
    assert _hands_on_vector(v, _p(hands_on_band="moderate"), CFG) == 55
    assert _hands_on_vector(v, _p(hands_on_band="light"), CFG) == 20
    assert _hands_on_vector(v, _p(hands_on_band="none"), CFG) == 0


def test_hands_on_unknown_on_either_side_is_zero():
    assert _hands_on_vector(_v(), _p(hands_on_band="deep"), CFG) == 0
    v = _v(hands_on={"required_level": "deep"})
    assert _hands_on_vector(v, _p(), CFG) == 0


def test_domain_exact_match():
    v = _v(domain={"industry": "gaming"})
    assert _domain_vector(v, _p(domains=["gaming", "fintech"]), CFG) == 100


def test_domain_adjacent_match():
    v = _v(domain={"industry": "igaming"})
    assert _domain_vector(v, _p(domains=["gaming"]), CFG) == 60


def test_domain_unrelated():
    v = _v(domain={"industry": "healthtech"})
    assert _domain_vector(v, _p(domains=["gaming"]), CFG) == 25


def test_domain_unknown_industry_is_zero():
    assert _domain_vector(_v(), _p(domains=["gaming"]), CFG) == 0


def test_domain_empty_candidate_profile_is_zero_not_other():
    # Пустой профиль — это «неизвестно» на стороне кандидата, а не «не совпало».
    v = _v(domain={"industry": "gaming"})
    assert _domain_vector(v, _p(domains=[]), CFG) == 0


def test_stack_not_required_is_full():
    # ФАКТ «технических требований не заявлено» — пустое требование покрыто полностью.
    v = _v(stack={"required": False})
    assert _stack_vector(v, _p(skills=[]), CFG) == 100


def test_stack_full_overlap():
    v = _v(stack={"required": True, "technologies": ["Python", "Playwright"]})
    assert _stack_vector(v, _p(skills=["python", "playwright", "sql"]), CFG) == 100


def test_stack_partial_overlap_is_share():
    v = _v(stack={"required": True,
                  "technologies": ["Python", "Playwright", "Kubernetes", "Go"]})
    assert _stack_vector(v, _p(skills=["Python", "Playwright"]), CFG) == 50


def test_stack_unknown_is_zero():
    # required=None — «неизвестно, есть ли требование» → 0 (правило §4.1).
    assert _stack_vector(_v(), _p(skills=["Python"]), CFG) == 0


def test_seniority_same_band_is_full():
    assert _seniority_vector("Head of QA", _p(seniority_band="head"), GATES, CFG) == 100


def test_seniority_one_step_away():
    assert _seniority_vector("QA Lead", _p(seniority_band="head"), GATES, CFG) == 60


def test_seniority_unknown_is_zero_not_excluded():
    # fit-1 исключал ось из знаменателя; fit-2 ставит 0 (решение владельца).
    assert _seniority_vector("QA Engineer", _p(seniority_band="head"), GATES, CFG) == 0
    assert _seniority_vector("QA Lead", _p(seniority_band=None), GATES, CFG) == 0


def test_role_family_overlap_is_full_without_multiplier():
    # Множители role_family_multipliers убраны: qa больше не даёт 120.
    assert _role_family_vector("QA Manager", _p(roles=["QA Manager"]), GATES) == 100


def test_role_family_word_boundary_fallback():
    # Роль кандидата совпадает с title текстуально, но НИ ОДНА сторона не размечена
    # в семью боевого config/triage_gates.json — единственный способ попасть в
    # фолбэк-ветку. Пары вроде "Delivery" для этого не годятся: слово само является
    # ключевым словом семьи delivery, что даёт полное совпадение (100), а не фолбэк.
    assert _role_family_vector("Head of Operations", _p(roles=["Operations"]),
                               GATES) == 50


def test_role_family_no_match_is_zero():
    assert _role_family_vector("Chef de Cuisine", _p(roles=["QA"]), GATES) == 0


def test_geo_global_remote_is_full():
    assert _geo_mode_vector("Worldwide", _p(), GATES, CFG, "remote") == 100


def test_geo_regional_remote():
    assert _geo_mode_vector("Berlin, Germany", _p(locations=["Europe"]), GATES, CFG,
                            "remote") == 90


def test_geo_hybrid_and_onsite():
    p = _p(locations=["Europe"])
    assert _geo_mode_vector("Berlin, Germany", p, GATES, CFG, "hybrid") == 70
    assert _geo_mode_vector("Berlin, Germany", p, GATES, CFG, "onsite") == 60


def test_geo_unknown_is_zero():
    assert _geo_mode_vector(None, _p(), GATES, CFG, "remote") == 0


def test_geo_known_region_unknown_work_mode_is_zero():
    # Регион разобран, а режим работы — нет. Это неизвестность, а не онсайт по
    # умолчанию: молчаливая подстановка режима завышала бы вектор на пустом месте.
    assert _geo_mode_vector("Berlin, Germany", _p(locations=["Europe"]), GATES, CFG,
                            None) == 0


def test_stack_required_but_no_technologies_extracted_is_zero():
    # «Стек требуется, но какой — не извлекли» — неизвестность (0), а не полное
    # покрытие. Граница отличается от required=None и заслуживает явной проверки.
    v = _v(stack={"required": True, "technologies": []})
    assert _stack_vector(v, _p(skills=["Python"]), CFG) == 0
