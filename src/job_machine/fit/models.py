"""Typed inputs and sanitized failures for vacancy fit."""
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class FitFact:
    fact_id: str
    text: str
    status: str
    source: str

    def __post_init__(self):
        if self.status not in {"verified", "approximate", "unknown"}:
            raise ValueError("invalid_fact_status")


@dataclass(frozen=True)
class FitInput:
    candidate_id: str
    vacancy_id: UUID
    job_text: str
    facts: tuple[FitFact, ...]


@dataclass(frozen=True)
class FitResult:
    score: int
    model: str
    rubric_version: str


class FitError(Exception):
    """Only diagnostic codes are exposed; never include request/response data."""

    def __init__(self, code: str, retryable: bool = False, retry_after_seconds: float | None = None):
        self.code = code
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds
        super().__init__(code)
