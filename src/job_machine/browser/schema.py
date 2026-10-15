"""Pydantic-модели запросов/ответов браузерного воркера."""

from pydantic import BaseModel, model_validator


class FormField(BaseModel):
    name: str
    field_type: str                 # text|email|select|checkbox|file|textarea|...
    label: str | None = None
    group_label: str | None = None  # question-level label (fieldset/legend/sibling), НЕ per-option label
    required: bool = False
    options: list[str] = []


class FormSchema(BaseModel):
    url: str
    fields: list[FormField] = []
    file_inputs: list[str] = []         # name file-инпутов
    consent_checkboxes: list[str] = []  # чекбоксы рядом с consent-текстом
    submit_buttons: list[str] = []      # кандидаты на submit (для плана 5)


class SessionInfo(BaseModel):
    session_id: str
    status: str                     # open
    current_url: str | None = None


class InspectRequest(BaseModel):
    session_id: str
    url: str | None = None
    navigate: bool = True    # False — читать текущее состояние страницы без page.goto
                              # (используется resume_after_handoff: повторная навигация
                              # сбросила бы cookies/anti-bot токены после ручной CAPTCHA)

    @model_validator(mode="after")
    def _url_required_when_navigating(self):
        if self.navigate and self.url is None:
            raise ValueError("url обязателен при navigate=True")
        return self


class InspectResult(BaseModel):
    blocker: str | None = None
    form_schema: FormSchema | None = None
    screenshot_path: str | None = None


class ContentRequest(BaseModel):
    session_id: str
    url: str


class ContentResult(BaseModel):
    html: str


class FillRequest(BaseModel):
    session_id: str
    fields: dict[str, str] = {}
    resume_path: str | None = None
    consent_checks: list[str] = []


class FillResult(BaseModel):
    filled: list[str] = []
    resume_attached: bool = False
    stopped_before_submit: bool = True
    screenshot_path: str | None = None
    trace_path: str | None = None
    unmatched: list[str] = []          # поля, которые не удалось заполнить (напр. select без опции)


class PdfRequest(BaseModel):
    html: str


class SubmitRequest(BaseModel):
    session_id: str
    fields: dict[str, str] = {}
    resume_path: str | None = None
    consent_checks: list[str] = []


class SubmitResult(BaseModel):
    submitted: bool = False
    click_performed: bool = False       # клик по submit физически выполнен
    confirmation_url: str | None = None
    confirmation_signal: str | None = None  # чем подтверждено: confirmation_url|thank_you_text
    form_absent: bool = False           # форма исчезла со страницы после клика
    errors_absent: bool = False         # на странице нет сообщений об ошибках
    screenshot_path: str | None = None
    unmatched: list[str] = []       # поля, не заполненные при попытке (см. FillResult.unmatched)
    failure_signal: str | None = None  # что именно провалило submit: unmatched|native_invalid|aria_invalid


def submission_proof_missing(result) -> list[str]:
    """Какие части долговечного доказательства подачи отсутствуют.

    Пустой список = подачу можно засчитать. Любой непустой = только `unknown`.
    Порог намеренно высокий: живой инцидент 23.07.2026 дал 145+ ложных
    submitted именно потому, что доказательством считался сам факт клика.
    """
    checks = (
        ("click_performed", bool(getattr(result, "click_performed", False))),
        ("confirmation_signal",
         bool(str(getattr(result, "confirmation_signal", "") or "").strip())),
        ("form_absent", getattr(result, "form_absent", False) is True),
        ("errors_absent", getattr(result, "errors_absent", False) is True),
        ("screenshot_path",
         bool(str(getattr(result, "screenshot_path", "") or "").strip())),
    )
    return [name for name, present in checks if not present]


class HandoffRequest(BaseModel):
    """Запрос на передачу живой сессии человеку (CAPTCHA/MFA)."""
    url: str


class HandoffResult(BaseModel):
    """Результат создания handoff-сессии."""
    session_id: str
    status: str                  # всегда "handoff"
    novnc_url: str | None = None  # ссылка на noVNC (если NOVNC_BASE_URL задан)
