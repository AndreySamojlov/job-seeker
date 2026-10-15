from dataclasses import dataclass

from pydantic import BaseModel


class RawSignal(BaseModel):
    company: str
    title: str
    url: str
    location: str | None = None
    description: str | None = None
    date_posted: str | None = None


class PostingEvidence(BaseModel):
    title: str
    url: str
    location: str | None = None
    found_at: str
    explicit_global: bool


@dataclass
class SearchRunResult:
    signals: list[RawSignal]
    failed_roles: list[str]
