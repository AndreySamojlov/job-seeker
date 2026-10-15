import pathlib

import pytest

SAMPLE_FORM = (
    pathlib.Path(__file__).resolve().parents[2]
    / "src" / "job_machine" / "browser" / "fixtures" / "sample_form.html"
)

SAMPLE_FORM_NO_BUTTON_TYPE = (
    pathlib.Path(__file__).resolve().parents[2]
    / "src" / "job_machine" / "browser" / "fixtures" / "sample_form_no_button_type.html"
)


@pytest.fixture
def sample_form_url():
    """file:// URI встроенной тест-формы."""
    return SAMPLE_FORM.as_uri()


@pytest.fixture
def sample_form_no_button_type_url():
    """file:// URI тест-формы с <button> без явного type (как на Ashby/Greenhouse)."""
    return SAMPLE_FORM_NO_BUTTON_TYPE.as_uri()


@pytest.fixture
async def browser_manager(tmp_path):
    """Запущенный SessionManager (headless), артефакты во временную папку."""
    from job_machine.browser.session import SessionManager

    mgr = SessionManager(headless=True, artifact_dir=tmp_path)
    await mgr.start()
    try:
        yield mgr
    finally:
        await mgr.shutdown()


GREENHOUSE_FORM = (
    pathlib.Path(__file__).resolve().parents[2]
    / "src" / "job_machine" / "browser" / "fixtures" / "greenhouse_form.html"
)


@pytest.fixture
def greenhouse_form_url():
    """file:// URI GH-подобной формы с именами job_application[...]."""
    return GREENHOUSE_FORM.as_uri()


GREENHOUSE_CHECKBOX_CONSENT_FORM = (
    pathlib.Path(__file__).resolve().parents[2]
    / "src" / "job_machine" / "browser" / "fixtures" / "greenhouse_checkbox_consent_form.html"
)


@pytest.fixture
def greenhouse_checkbox_consent_form_url():
    """file:// URI формы с GH-паттерном label-перед-fieldset для одно-опционного чекбокса."""
    return GREENHOUSE_CHECKBOX_CONSENT_FORM.as_uri()


INVISIBLE_RECAPTCHA_FORM = (
    pathlib.Path(__file__).resolve().parents[2]
    / "src" / "job_machine" / "browser" / "fixtures" / "invisible_recaptcha_form.html"
)


@pytest.fixture
def invisible_recaptcha_form_url():
    """file:// URI формы с фоновым invisible reCAPTCHA (size=invisible), без челленджа."""
    return INVISIBLE_RECAPTCHA_FORM.as_uri()


VISIBLE_RECAPTCHA_FORM = (
    pathlib.Path(__file__).resolve().parents[2]
    / "src" / "job_machine" / "browser" / "fixtures" / "visible_recaptcha_form.html"
)


@pytest.fixture
def visible_recaptcha_form_url():
    """file:// URI формы с видимым reCAPTCHA v2 checkbox (size=normal)."""
    return VISIBLE_RECAPTCHA_FORM.as_uri()


HCAPTCHA_HIDDEN_CHALLENGE_FORM = (
    pathlib.Path(__file__).resolve().parents[2]
    / "src" / "job_machine" / "browser" / "fixtures" / "hcaptcha_hidden_challenge_form.html"
)


@pytest.fixture
def hcaptcha_hidden_challenge_form_url():
    """file:// URI формы hCaptcha с преднагруженным, но скрытым challenge-iframe."""
    return HCAPTCHA_HIDDEN_CHALLENGE_FORM.as_uri()


HCAPTCHA_VISIBLE_CHALLENGE_FORM = (
    pathlib.Path(__file__).resolve().parents[2]
    / "src" / "job_machine" / "browser" / "fixtures" / "hcaptcha_visible_challenge_form.html"
)


@pytest.fixture
def hcaptcha_visible_challenge_form_url():
    """file:// URI формы hCaptcha с реально показанным challenge-iframe."""
    return HCAPTCHA_VISIBLE_CHALLENGE_FORM.as_uri()


FORMLESS_FIELDS = (
    pathlib.Path(__file__).resolve().parents[2]
    / "src" / "job_machine" / "browser" / "fixtures" / "formless_fields.html"
)


@pytest.fixture
def formless_fields_url():
    """file:// URI страницы с реальными полями БЕЗ обёртки <form> (как у Ashby)."""
    return FORMLESS_FIELDS.as_uri()


TWO_STEP_APPLY_LANDING = (
    pathlib.Path(__file__).resolve().parents[2]
    / "src" / "job_machine" / "browser" / "fixtures" / "two_step_apply_landing.html"
)


@pytest.fixture
def two_step_apply_landing_url():
    """file:// URI страницы-описания с отдельной ссылкой на форму (как Lever/N26)."""
    return TWO_STEP_APPLY_LANDING.as_uri()


TWO_STEP_APPLY_LANDING_WITH_DECOY_BUTTON = (
    pathlib.Path(__file__).resolve().parents[2]
    / "src" / "job_machine" / "browser" / "fixtures"
    / "two_step_apply_landing_with_decoy_button.html"
)


@pytest.fixture
def two_step_apply_landing_with_decoy_button_url():
    """file:// URI лендинга, где декой-кнопка 'Apply with LinkedIn' (без href) идёт
    в document order ПЕРЕД настоящей ссылкой 'Apply for this job'."""
    return TWO_STEP_APPLY_LANDING_WITH_DECOY_BUTTON.as_uri()


DELAYED_RENDER_FIELDS = (
    pathlib.Path(__file__).resolve().parents[2]
    / "src" / "job_machine" / "browser" / "fixtures" / "delayed_render_fields.html"
)


@pytest.fixture
def delayed_render_fields_url():
    """file:// URI страницы, которая дорисовывает форму через JS spустя ~800ms
    (как асинхронный рендер Ashby-style SPA после domcontentloaded)."""
    return DELAYED_RENDER_FIELDS.as_uri()


CSP_DELAYED_RENDER_FIELDS = (
    pathlib.Path(__file__).resolve().parents[2]
    / "src" / "job_machine" / "browser" / "fixtures" / "csp_delayed_render_fields.html"
)


@pytest.fixture
def csp_delayed_render_fields_url():
    """file:// URI той же отложенной формы, но со строгим CSP script-src без
    'unsafe-eval' (meta-тег — реально применяется браузером и к file://) — как на
    живом Ashby (инцидент 2026-07-17). wait_for_function ломается об эту CSP
    (EvalError), wait_for_selector — нет (другой CDP-механизм, не JS-eval)."""
    return CSP_DELAYED_RENDER_FIELDS.as_uri()


STATIC_COMBOBOX_FORM = (
    pathlib.Path(__file__).resolve().parents[2]
    / "src" / "job_machine" / "browser" / "fixtures" / "greenhouse_static_combobox_form.html"
)


@pytest.fixture
def static_combobox_form_url():
    """file:// URI react-select-комбобокса с готовыми опциями сразу после клика."""
    return STATIC_COMBOBOX_FORM.as_uri()


REQUIRED_SELECT_SHELL_FORM = (
    pathlib.Path(__file__).resolve().parents[2]
    / "src" / "job_machine" / "browser" / "fixtures"
    / "greenhouse_required_select_shell_form.html"
)


@pytest.fixture
def required_select_shell_form_url():
    """file:// URI живой разметки Greenhouse, где требуемость вопроса лежит на
    безымянной заглушке React Select, а лейбл — на соседнем role=combobox."""
    return REQUIRED_SELECT_SHELL_FORM.as_uri()


DEBOUNCED_GEO_AUTOCOMPLETE_FORM = (
    pathlib.Path(__file__).resolve().parents[2]
    / "src" / "job_machine" / "browser" / "fixtures"
    / "greenhouse_debounced_geo_autocomplete_form.html"
)


@pytest.fixture
def debounced_geo_autocomplete_form_url():
    """file:// URI debounced geo-autocomplete-комбобокса (fake geocoding, Addepar-паттерн)."""
    return DEBOUNCED_GEO_AUTOCOMPLETE_FORM.as_uri()
