from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class GuardContext:
    """Уже загруженное структурное состояние, которое читают guards.

    Контейнер наполняет вызывающий слой (воркер/контроллер); guard не ходит в
    БД сам, поэтому тестируется на фабричном ctx. Все поля опциональны — guard
    читает только то, что ему нужно.

    Поля:
      application          dict-строка application (payload_hash, application_id, ...)
      approval             dict-строка approval (approval_status, approval_token,
                           payload_hash, expires_at)
      resume_artifact      dict резюме-артефакта (content_hash, ...)
      disclosed_resume_hash раскрытый/одобренный content_hash резюме
      summary_artifacts    список dict-артефактов (ищем artifact_type='approval_summary')
      browser_state        dict состояния браузера (см. guards/browser.py)
      now                  datetime для проверки expiry (инъекция, не datetime.now())
      trace_id             trace_id для audit
    """

    application: dict[str, Any] | None = None
    approval: dict[str, Any] | None = None
    resume_artifact: dict[str, Any] | None = None
    disclosed_resume_hash: str | None = None
    summary_artifacts: list[dict[str, Any]] = field(default_factory=list)
    browser_state: dict[str, Any] | None = None
    now: datetime | None = None
    trace_id: str | None = None
