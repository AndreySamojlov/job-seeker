import typing

import pytest
from pydantic import ValidationError

from job_machine.triage.models import (
    ClaimRecord, HardRequirementMatch, TriageInput, TriageVerdict,
    STRUCTURED_OUTPUT_SCHEMA, INDUSTRY_ENUM, HANDS_ON_LEVELS,
    Eligibility, LanguageRequirement, WorkAuthorization, OnsiteRequirement,
    DomainFacts, StackFacts, HandsOnFacts,
)


def test_claim_record_minimal():
    c = ClaimRecord(claim_id="C-001", claim_text="13+ years", status="verified")
    assert c.proof is None and c.safe_use is None


def test_triage_verdict_parses_full_payload():
    v = TriageVerdict(
        vacancy_id="11111111-1111-1111-1111-111111111111",
        verdict="apply_with_caveat",
        fit_summary="Strong QA leadership match; no hands-on coding.",
        hard_requirements=[
            {"requirement": "10+ yrs QA", "status": "strong", "evidence_claim_ids": ["C-003"]},
            {"requirement": "commercial Python coding", "status": "gap", "evidence_claim_ids": []},
        ],
        material_unknowns=["work authorization for EU"],
        overclaim_risks=["do not claim hands-on commercial coding (C-018)"],
    )
    assert v.verdict == "apply_with_caveat"
    assert v.hard_requirements[1].status == "gap"
    assert v.material_unknowns == ["work authorization for EU"]


def test_triage_verdict_rejects_bad_verdict():
    with pytest.raises(ValidationError):
        TriageVerdict(vacancy_id="x", verdict="maybe", fit_summary="", hard_requirements=[])


def test_structured_output_schema_lists_verdict_enum():
    props = STRUCTURED_OUTPUT_SCHEMA["properties"]
    assert props["verdict"]["enum"] == ["apply", "apply_with_caveat", "skip"]
    assert "vacancy_id" in STRUCTURED_OUTPUT_SCHEMA["required"]


def test_triage_verdict_accepts_valid_skip_category():
    v = TriageVerdict(
        vacancy_id="11111111-1111-1111-1111-111111111111",
        verdict="skip",
        fit_summary="Requires active government security clearance.",
        hard_requirements=[
            {"requirement": "active clearance", "status": "gap", "evidence_claim_ids": []},
        ],
        skip_category="clearance_or_citizenship",
    )
    assert v.skip_category == "clearance_or_citizenship"


def test_triage_verdict_defaults_skip_category_to_none():
    v = TriageVerdict(
        vacancy_id="x", verdict="apply_with_caveat", fit_summary="",
        hard_requirements=[],
    )
    assert v.skip_category is None


def test_triage_verdict_rejects_invalid_skip_category():
    with pytest.raises(ValidationError):
        TriageVerdict(
            vacancy_id="x", verdict="skip", fit_summary="", hard_requirements=[],
            skip_category="no_kotlin_experience",
        )


def test_structured_output_schema_lists_skip_category_enum():
    props = STRUCTURED_OUTPUT_SCHEMA["properties"]
    assert props["skip_category"]["enum"] == [
        "mandatory_language", "license_or_qualification", "clearance_or_citizenship",
        "onsite_location", "domain_mismatch",
    ]
    # НЕ обязательное поле схемы — LLM может забыть его на skip, это трактуется
    # бэкстопом (Task 2) как «категория не доказана», а не как ошибка валидации.
    assert "skip_category" not in STRUCTURED_OUTPUT_SCHEMA["required"]


def test_verdict_v2_defaults_are_empty_not_none():
    v = TriageVerdict(vacancy_id="v1", verdict="apply", fit_summary="x",
                      hard_requirements=[])
    assert v.eligibility.required_languages == []
    assert v.eligibility.work_authorization.requires_clearance is None
    assert v.eligibility.onsite.onsite_required is None
    assert v.domain.industry is None
    assert v.stack.required is None and v.stack.technologies == []
    assert v.hands_on.required_level is None


def test_requirement_importance_defaults_to_must():
    r = HardRequirementMatch(requirement="10y QA", status="strong")
    assert r.importance == "must"
    r2 = HardRequirementMatch(requirement="k8s", status="gap", importance="nice")
    assert r2.importance == "nice"


def test_verdict_v2_parses_full_facts():
    v = TriageVerdict(
        vacancy_id="v1", verdict="apply_with_caveat", fit_summary="x",
        hard_requirements=[{"requirement": "QA lead", "status": "strong",
                            "importance": "must"}],
        eligibility={
            "required_languages": [{"language": "German", "level": "C1",
                                    "mandatory": True}],
            "work_authorization": {"sponsorship_offered": False,
                                   "requires_local_right": True},
            "onsite": {"onsite_required": True, "city": "Munich",
                       "relocation_supported": False},
        },
        domain={"industry": "fintech", "product_type": "payments"},
        stack={"required": True, "technologies": ["Python", "Playwright"]},
        hands_on={"required_level": "moderate", "evidence": "writes test code"},
    )
    assert v.eligibility.required_languages[0].mandatory is True
    assert v.domain.industry == "fintech"
    assert v.stack.technologies == ["Python", "Playwright"]
    assert v.hands_on.required_level == "moderate"


def test_unknown_industry_degrades_to_none_not_error():
    # Незнакомый ярлык не должен ронять apply: трактуем как «неизвестно» (0 баллов).
    v = TriageVerdict(vacancy_id="v1", verdict="apply", fit_summary="x",
                      hard_requirements=[], domain={"industry": "pet-rocks"})
    assert v.domain.industry is None


def test_schema_matches_v2_model():
    props = STRUCTURED_OUTPUT_SCHEMA["properties"]
    assert props["hard_requirements"]["items"]["properties"]["importance"]["enum"] == \
        ["must", "nice"]
    assert props["domain"]["properties"]["industry"]["enum"] == INDUSTRY_ENUM
    assert props["hands_on"]["properties"]["required_level"]["enum"] == \
        ["none", "light", "moderate", "deep"]
    assert "eligibility" in props and "stack" in props


def test_language_mandatory_defaults_to_unknown_not_false():
    r = LanguageRequirement(language="German")
    assert r.mandatory is None


def test_hands_on_levels_constant_matches_model_literal():
    # HANDS_ON_LEVELS кормит только JSON-схему; Literal в модели — источник правды.
    # Тест ловит расхождение, если шкалу поправят в одном месте и забудут в другом.
    ann = HandsOnFacts.model_fields["required_level"].annotation
    literal_values = list(typing.get_args(typing.get_args(ann)[0]))
    assert literal_values == HANDS_ON_LEVELS


def test_schema_has_all_v2_model_fields():
    # Листовые enum-тесты (test_schema_matches_v2_model) не ловят выпавшее целиком
    # свойство — структурная проверка паритета поле-в-поле для каждой новой модели.
    props = STRUCTURED_OUTPUT_SCHEMA["properties"]
    model_to_schema_props = {
        Eligibility: props["eligibility"]["properties"],
        LanguageRequirement: props["eligibility"]["properties"]
                              ["required_languages"]["items"]["properties"],
        WorkAuthorization: props["eligibility"]["properties"]["work_authorization"]
                            ["properties"],
        OnsiteRequirement: props["eligibility"]["properties"]["onsite"]["properties"],
        DomainFacts: props["domain"]["properties"],
        StackFacts: props["stack"]["properties"],
        HandsOnFacts: props["hands_on"]["properties"],
    }
    for model, schema_props in model_to_schema_props.items():
        for field_name in model.model_fields:
            assert field_name in schema_props, \
                f"{model.__name__}.{field_name} missing from STRUCTURED_OUTPUT_SCHEMA"


def test_industry_normalises_case_and_spacing():
    """Ревью 2026-08-15: 'Gaming' молча деградировало в None, и вектор domain терял
    15 баллов композита без следа в флагах."""
    assert DomainFacts(industry="Gaming").industry == "gaming"
    assert DomainFacts(industry="  fintech ").industry == "fintech"
    assert DomainFacts(industry="nonsense").industry is None
    assert DomainFacts(industry=None).industry is None
