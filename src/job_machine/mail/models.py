from typing import Literal

from pydantic import BaseModel


class EmailInput(BaseModel):
    """Одно новое письмо, как его отдаёт imap_client (без истории thread)."""
    uid: int
    from_addr: str
    subject: str
    body: str


class ApplicationRef(BaseModel):
    """Активная заявка кандидата — контекст для матчинга LLM."""
    application_id: str
    candidate_id: str
    company: str
    role: str


class ReplyClassification(BaseModel):
    """Structured output LLM: матч заявки + статус воронки."""
    application_id: str | None = None
    candidate_id: str | None = None
    category: Literal["rejected", "interview_scheduled", "other"]
    confidence: float


MAIL_STRUCTURED_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "application_id": {"type": ["string", "null"]},
        "candidate_id": {"type": ["string", "null"]},
        "category": {
            "type": "string",
            "enum": ["rejected", "interview_scheduled", "other"],
        },
        "confidence": {"type": "number"},
    },
    "required": ["category", "confidence"],
}
