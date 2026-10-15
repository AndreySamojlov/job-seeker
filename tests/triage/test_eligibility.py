from job_machine.triage.eligibility import EligibilityResult, check_eligibility
from job_machine.triage.gates import CandidateProfile
from job_machine.triage.gates_config import GateConfig
from job_machine.triage.models import TriageVerdict


def _gate_cfg():
    return GateConfig(
        role_family_map={"qa": ["qa"]},
        level_bands=["junior", "mid", "senior", "lead", "head"],
        level_keywords={"lead": ["lead"]},
        level_up_tolerance=1, level_down_tolerance=3,
        geo_region_map={"europe": ["europe", "germany"]},
        geo_global_tokens=["worldwide"],
        company_daily_cap_default=5,
    )


def _profile(**kw):
    base = dict(roles=["QA"], locations=["Europe"], seniority_band="lead",
                company_daily_cap=5, languages=["English", "Russian"])
    base.update(kw)
    return CandidateProfile(**base)


def _verdict(**elig):
    return TriageVerdict(vacancy_id="v1", verdict="apply", fit_summary="x",
                         hard_requirements=[], eligibility=elig)


def test_clean_verdict_is_not_blocked():
    r = check_eligibility(_verdict(), _profile(), _gate_cfg())
    assert isinstance(r, EligibilityResult)
    assert r.blocked is False and r.category is None and r.unknowns == []


def test_mandatory_language_candidate_lacks_blocks():
    r = check_eligibility(
        _verdict(required_languages=[{"language": "German", "level": "C1",
                                      "mandatory": True}]),
        _profile(), _gate_cfg())
    assert r.blocked is True
    assert r.category == "mandatory_language"
    assert "German" in r.reason


def test_mandatory_language_candidate_has_does_not_block():
    r = check_eligibility(
        _verdict(required_languages=[{"language": "english", "mandatory": True}]),
        _profile(), _gate_cfg())
    assert r.blocked is False


def test_non_mandatory_language_does_not_block():
    r = check_eligibility(
        _verdict(required_languages=[{"language": "German", "mandatory": False}]),
        _profile(), _gate_cfg())
    assert r.blocked is False
    assert r.unknowns == []


def test_language_with_unknown_mandatory_flag_discloses():
    # mandatory=None — «неизвестно, обязателен ли». Не блокируем, но владелец
    # обязан это увидеть, иначе реальный языковой блокер пройдёт молча.
    r = check_eligibility(
        _verdict(required_languages=[{"language": "German"}]),
        _profile(), _gate_cfg())
    assert r.blocked is False
    assert any("German" in u for u in r.unknowns)


def test_clearance_blocks():
    r = check_eligibility(
        _verdict(work_authorization={"requires_clearance": True}),
        _profile(), _gate_cfg())
    assert r.blocked is True and r.category == "clearance_or_citizenship"


def test_local_right_without_sponsorship_blocks():
    r = check_eligibility(
        _verdict(work_authorization={"requires_local_right": True,
                                     "sponsorship_offered": False}),
        _profile(), _gate_cfg())
    assert r.blocked is True and r.category == "clearance_or_citizenship"


def test_local_right_with_unknown_sponsorship_discloses_not_blocks():
    # Неизвестность в фазе допуска РАСКРЫВАЕТСЯ, а не блокирует.
    r = check_eligibility(
        _verdict(work_authorization={"requires_local_right": True}),
        _profile(), _gate_cfg())
    assert r.blocked is False
    assert any("sponsorship" in u.lower() for u in r.unknowns)


def test_onsite_outside_allowed_region_blocks():
    r = check_eligibility(
        _verdict(onsite={"onsite_required": True, "city": "Austin, Texas",
                         "relocation_supported": False}),
        _profile(), _gate_cfg())
    assert r.blocked is True and r.category == "onsite_location"


def test_onsite_inside_allowed_region_does_not_block():
    r = check_eligibility(
        _verdict(onsite={"onsite_required": True, "city": "Berlin, Germany",
                         "relocation_supported": False}),
        _profile(), _gate_cfg())
    assert r.blocked is False


def test_onsite_with_relocation_support_does_not_block():
    r = check_eligibility(
        _verdict(onsite={"onsite_required": True, "city": "Austin, Texas",
                         "relocation_supported": True}),
        _profile(), _gate_cfg())
    assert r.blocked is False


def test_onsite_with_unknown_relocation_discloses_not_blocks():
    # Про релокацию не сказано ничего — это не отказ в ней. Блокировать можно только
    # по установленному False, иначе неизвестность выносит приговор (нарушение инварианта).
    r = check_eligibility(
        _verdict(onsite={"onsite_required": True, "city": "Austin, Texas"}),
        _profile(), _gate_cfg())
    assert r.blocked is False
    assert any("relocation support is not stated" in u for u in r.unknowns)


def test_onsite_without_city_discloses_not_blocks():
    r = check_eligibility(
        _verdict(onsite={"onsite_required": True, "relocation_supported": False}),
        _profile(), _gate_cfg())
    assert r.blocked is False
    assert any("onsite" in u.lower() for u in r.unknowns)
