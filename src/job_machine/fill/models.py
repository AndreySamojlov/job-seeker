"""Контракты fill-воркера: результат маппинга и сводка прогона."""

from pydantic import BaseModel, Field


class MappingResult(BaseModel):
    """Результат детерминированного маппинга disclosed answers в поля формы.

    fields            — {имя_поля_формы: значение} для текст/select/прочих (без файла).
    resume_field      — имя file-инпута под резюме (прикрепляется отдельно), либо None.
    unmatched_required — обязательные поля формы без честного значения → блокер.
    matched           — vault-поля, которые удалось приложить (для observability).
    """
    fields: dict[str, str] = Field(default_factory=dict)
    resume_field: str | None = None
    unmatched_required: list[str] = Field(default_factory=list)
    matched: list[str] = Field(default_factory=list)
    auto_consents: list[str] = Field(default_factory=list)


class FillRunSummary(BaseModel):
    """Сводка прогона run_fill."""
    pulled: int = 0
    pre_submit_ready: int = 0
    agent_fill_pending: int = 0
    blocked: int = 0
    errors: int = 0
