from typing import Literal

from pydantic import BaseModel, Field, field_validator


class ClaimRecord(BaseModel):
    claim_id: str
    claim_text: str
    status: Literal["verified", "approximate", "unknown"]
    proof: str | None = None
    safe_use: str | None = None


# Закрытый перечень индустрий: код сверяет ЯРЛЫКИ, а не свободный текст — иначе
# вектор domain становится недетерминированным. Незнакомый ярлык деградирует в None
# (= «неизвестно» = 0 баллов), а не роняет apply.
INDUSTRY_ENUM = [
    "gaming", "igaming", "fintech", "banking", "crypto", "ecommerce",
    "marketplace", "saas_b2b", "healthtech", "edtech", "adtech", "logistics",
    "telecom", "consulting", "media", "travel", "hardware", "gov_public", "other",
]

HANDS_ON_LEVELS = ["none", "light", "moderate", "deep"]


class HardRequirementMatch(BaseModel):
    requirement: str
    status: Literal["strong", "partial", "gap", "unknown"]
    # must/nice — вес требования в векторе requirements. Дефолт 'must': при
    # неразмеченном требовании безопаснее считать его обязательным, чем занизить
    # вес реального блокера.
    importance: Literal["must", "nice"] = "must"
    evidence_claim_ids: list[str] = []
    note: str | None = None


class LanguageRequirement(BaseModel):
    language: str
    level: str | None = None
    # mandatory=True — обязателен, mandatory=False — ФАКТ «не обязателен»,
    # mandatory=None — неизвестно (не молчать как False; фаза допуска должна
    # видеть неопределённость и раскрыть её в material_unknowns).
    mandatory: bool | None = None


class WorkAuthorization(BaseModel):
    sponsorship_offered: bool | None = None
    requires_local_right: bool | None = None
    requires_clearance: bool | None = None


class OnsiteRequirement(BaseModel):
    onsite_required: bool | None = None
    city: str | None = None
    relocation_supported: bool | None = None


class Eligibility(BaseModel):
    required_languages: list[LanguageRequirement] = []
    work_authorization: WorkAuthorization = Field(default_factory=WorkAuthorization)
    onsite: OnsiteRequirement = Field(default_factory=OnsiteRequirement)


class DomainFacts(BaseModel):
    industry: str | None = None
    product_type: str | None = None

    @field_validator("industry")
    @classmethod
    def _known_industry_only(cls, v):
        # Регистр и пробелы нормализуем ДО сверки: enum в JSON-схеме ничего не
        # принуждает на стороне извлекающего агента, и 'Gaming' молча деградировало
        # бы в None — вектор domain терял бы 15 баллов композита без следа в флагах.
        if not isinstance(v, str):
            return None
        v = v.strip().lower()
        return v if v in INDUSTRY_ENUM else None


class StackFacts(BaseModel):
    # required=False — ФАКТ «технических требований не заявлено» (вектор = 100),
    # required=None — «неизвестно» (вектор = 0). См. §4.1 спеки.
    required: bool | None = None
    technologies: list[str] = []


class HandsOnFacts(BaseModel):
    required_level: Literal["none", "light", "moderate", "deep"] | None = None
    evidence: str | None = None


class TriageInput(BaseModel):
    """Что воркер отдаёт n8n на каждую вакансию (детерминированно собрано).
    candidate_id — чей это input (нужен n8n /triage/pull_all, чтобы применить
    вердикт правильному кандидату). Default None — обратная совместимость."""
    vacancy_id: str
    candidate_id: str | None = None
    title: str | None = None
    company: str | None = None
    location: str | None = None
    work_mode: str | None = None
    job_text: str
    claims: list[ClaimRecord]


class TriageVerdict(BaseModel):
    """Structured output из n8n (DeepSeek). Валидируется на /triage/apply."""
    vacancy_id: str
    verdict: Literal["apply", "apply_with_caveat", "skip"]
    fit_summary: str
    hard_requirements: list[HardRequirementMatch]
    material_unknowns: list[str] = []
    overclaim_risks: list[str] = []
    # Обязательно по промпту при verdict='skip' — один из 5 категорических исключений
    # §3 CLAUDE.md. Отсутствие/None на skip трактуется бэкстопом apply_verdict (store.py)
    # как «категория не доказана» (funnel-quality-fixes 2026-07-15).
    skip_category: Literal[
        "mandatory_language", "license_or_qualification", "clearance_or_citizenship",
        "onsite_location", "domain_mismatch",
    ] | None = None
    eligibility: Eligibility = Field(default_factory=Eligibility)
    domain: DomainFacts = Field(default_factory=DomainFacts)
    stack: StackFacts = Field(default_factory=StackFacts)
    hands_on: HandsOnFacts = Field(default_factory=HandsOnFacts)


# JSON-схема для n8n Structured Output Parser. ДОЛЖНА совпадать с TriageVerdict.
STRUCTURED_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "vacancy_id": {"type": "string"},
        "verdict": {"type": "string", "enum": ["apply", "apply_with_caveat", "skip"]},
        "fit_summary": {"type": "string"},
        "hard_requirements": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "requirement": {"type": "string"},
                    "status": {"type": "string",
                               "enum": ["strong", "partial", "gap", "unknown"]},
                    "importance": {"type": "string", "enum": ["must", "nice"]},
                    "evidence_claim_ids": {"type": "array", "items": {"type": "string"}},
                    "note": {"type": "string"},
                },
                "required": ["requirement", "status"],
            },
        },
        "material_unknowns": {"type": "array", "items": {"type": "string"}},
        "overclaim_risks": {"type": "array", "items": {"type": "string"}},
        "skip_category": {
            "type": "string",
            "enum": ["mandatory_language", "license_or_qualification",
                     "clearance_or_citizenship", "onsite_location", "domain_mismatch"],
        },
        "eligibility": {
            "type": "object",
            "properties": {
                "required_languages": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "language": {"type": "string"},
                            "level": {"type": "string"},
                            "mandatory": {"type": "boolean"},
                        },
                        "required": ["language"],
                    },
                },
                "work_authorization": {
                    "type": "object",
                    "properties": {
                        "sponsorship_offered": {"type": "boolean"},
                        "requires_local_right": {"type": "boolean"},
                        "requires_clearance": {"type": "boolean"},
                    },
                },
                "onsite": {
                    "type": "object",
                    "properties": {
                        "onsite_required": {"type": "boolean"},
                        "city": {"type": "string"},
                        "relocation_supported": {"type": "boolean"},
                    },
                },
            },
        },
        "domain": {
            "type": "object",
            "properties": {
                "industry": {"type": "string", "enum": INDUSTRY_ENUM},
                "product_type": {"type": "string"},
            },
        },
        "stack": {
            "type": "object",
            "properties": {
                "required": {"type": "boolean"},
                "technologies": {"type": "array", "items": {"type": "string"}},
            },
        },
        "hands_on": {
            "type": "object",
            "properties": {
                "required_level": {"type": "string", "enum": HANDS_ON_LEVELS},
                "evidence": {"type": "string"},
            },
        },
    },
    "required": ["vacancy_id", "verdict", "fit_summary", "hard_requirements"],
}
