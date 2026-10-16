"""Provider answer and safe operational errors."""
from dataclasses import dataclass


@dataclass(frozen=True)
class JevReadinessAnswer:
    value: float
    model: str
    rubric_version: str


class ReadinessError(ValueError):
    def __init__(self, code: str, retryable: bool = False, retry_after_seconds: float | None = None):
        super().__init__(code)
        self.code = code
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds
