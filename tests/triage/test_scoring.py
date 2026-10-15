from job_machine.triage.gates import CandidateProfile
from job_machine.triage.gates_config import load_gate_config
from job_machine.triage.models import TriageVerdict
from job_machine.triage.score_config import load_score_config
from job_machine.triage.scoring import FitScore, compute_fit_score

CFG = load_score_config()
GATES = load_gate_config()


def _strong_profile(**kw):
    base = dict(roles=["Head of QA"], locations=["Europe"], seniority_band="head",
                company_daily_cap=5, languages=["English"], hands_on_band="light",
                domains=["gaming"], skills=["Python", "Playwright"])
    base.update(kw)
    return CandidateProfile(**base)


def _strong_verdict(**kw):
    base = dict(
        vacancy_id="v1", verdict="apply", fit_summary="x",
        hard_requirements=[{"requirement": "QA leadership", "status": "strong"},
                           {"requirement": "test automation", "status": "strong"}],
        domain={"industry": "gaming"},
        stack={"required": True, "technologies": ["Python", "Playwright"]},
        hands_on={"required_level": "light"},
    )
    base.update(kw)
    return TriageVerdict(**base)


def _fit(verdict, profile, title="Head of QA", location="Berlin, Germany",
         work_mode="remote"):
    return compute_fit_score(verdict, title, location, profile, GATES, CFG,
                             work_mode=work_mode)


def test_all_vectors_full_gives_band_a():
    fit = _fit(_strong_verdict(), _strong_profile())
    assert isinstance(fit, FitScore)
    assert fit.vectors == {"requirements": 100, "hands_on": 100, "domain": 100,
                           "stack": 100, "role_family": 100, "seniority": 100,
                           "geo_mode": 90}
    # 30+15+15+15+10+10+4.5 = 99.5 → round() к чётному даёт 100
    assert fit.score == 100
    assert fit.band == "A"
    assert fit.capped_by == []
    assert fit.version == "fit-2"


def test_every_vector_stays_in_denominator():
    # Голый вердикт без фактов: ни один вектор не исключается, композит близок к нулю.
    v = TriageVerdict(vacancy_id="v1", verdict="apply", fit_summary="x",
                      hard_requirements=[])
    fit = _fit(v, CandidateProfile(roles=[], locations=[], seniority_band=None,
                                   company_daily_cap=None),
               title=None, location=None, work_mode=None)
    assert set(fit.vectors) == set(CFG.weights)
    assert all(val == 0 for val in fit.vectors.values())
    assert fit.score == 0 and fit.band == "D"


def test_requirements_below_floor_caps_band_at_c():
    # Все прочие векторы сильные, но покрытие требований провалено → потолок C.
    v = _strong_verdict(hard_requirements=[
        {"requirement": "QA leadership", "status": "gap"},
        {"requirement": "test automation", "status": "gap"}])
    fit = _fit(v, _strong_profile())
    assert fit.vectors["requirements"] == 0
    assert "requirements" in fit.capped_by
    assert fit.band == "C"


def test_hands_on_below_floor_caps_band():
    v = _strong_verdict(hands_on={"required_level": "deep"})
    fit = _fit(v, _strong_profile(hands_on_band="none"))
    assert fit.vectors["hands_on"] == 0
    assert fit.capped_by == ["hands_on"]
    assert fit.band == "C"


def test_cap_does_not_promote_a_weak_band():
    # Потолок только опускает: заявка, честно набравшая D, не поднимается до C.
    v = TriageVerdict(vacancy_id="v1", verdict="apply", fit_summary="x",
                      hard_requirements=[{"requirement": "a", "status": "gap"}])
    fit = _fit(v, CandidateProfile(roles=[], locations=[], seniority_band=None,
                                   company_daily_cap=None),
               title=None, location=None, work_mode=None)
    assert fit.band == "D"


def test_unknown_requirements_raise_low_confidence_flag():
    v = _strong_verdict(hard_requirements=[
        {"requirement": "a", "status": "unknown"},
        {"requirement": "b", "status": "unknown"},
        {"requirement": "c", "status": "strong"}])
    fit = _fit(v, _strong_profile())
    assert "low_confidence" in fit.flags


def test_breakdown_is_json_serialisable_and_carries_capped_by():
    import json
    v = _strong_verdict(hands_on={"required_level": "deep"})
    fit = _fit(v, _strong_profile(hands_on_band="none"))
    payload = fit.breakdown()
    assert json.loads(json.dumps(payload))["capped_by"] == ["hands_on"]
    assert payload["vectors"]["hands_on"] == 0
