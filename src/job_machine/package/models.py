from typing import Literal

from pydantic import BaseModel

AnswerState = Literal["locked", "blocked", "optional-policy"]


class AnswerRecord(BaseModel):
    """Строка answer-vault."""
    field: str
    value: str
    state: AnswerState
    rule: str = ""


class DisclosedAnswer(BaseModel):
    """Locked-ответ, доступный к передаче и раскрытый в summary."""
    field: str
    value: str
    source: Literal["locked"] = "locked"


class DisclosedConsent(BaseModel):
    """Согласие/декларация по политике (decline/blank по умолчанию)."""
    field: str
    decision: str
    source: Literal["policy"] = "policy"


class UnresolvedFact(BaseModel):
    """Blocked-факт: раскрыт как предупреждение, НЕ передаётся, НЕ хешируется."""
    field: str
    rule: str = ""


class PackageInput(BaseModel):
    application_id: str
    company: str
    role: str
    destination_url: str
    ats_family: str | None = None
    fit_summary: str = ""
    hard_requirements: list[dict] = []
    # Честные оговорки из triage (политика disclosed-caveats §3): гэпы под требования
    # роли и риски переоценки — раскрываются в disclosed-summary, НЕ передаются в форму.
    material_unknowns: list[str] = []
    overclaim_risks: list[str] = []


class ResumeArtifact(BaseModel):
    filename: str
    path: str
    content_hash: str


class PackageManifest(BaseModel):
    """Машиночитаемый payload пакета."""
    application_id: str
    company: str
    role: str
    destination_url: str
    resume: ResumeArtifact
    answers: list[DisclosedAnswer]
    consents: list[DisclosedConsent]
    warnings: list[UnresolvedFact]
    fit_summary: str = ""
    hard_requirements: list[dict] = []
    material_unknowns: list[str] = []
    overclaim_risks: list[str] = []
    answers_hash: str
    consents_hash: str
    payload_hash: str
