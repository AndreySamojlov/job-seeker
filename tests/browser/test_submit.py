from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from job_machine.browser.app import create_app
from job_machine.browser.schema import SubmitResult, submission_proof_missing


class _FakePage:
    url = "https://example.com/confirmation?submitted=1"
    invalid_count = 0  # переопределяется в тестах на "браузер заблокировал submit"

    def __init__(self):
        self._last_selector = ""

    def locator(self, sel):
        self._last_selector = sel
        return self

    @property
    def first(self):
        return self

    async def count(self):
        # Ни одно фейковое поле не чекбокс — иначе fill_form уходит в чекбокс-ветку
        # (_check_option_in_group -> .nth(), которого у фейка нет).
        if 'type="checkbox"' in self._last_selector:
            return 0
        return 1

    async def evaluate(self, js):
        if "querySelectorAll(':invalid')" in js:
            return "native_invalid" if self.invalid_count else None
        return "input"

    async def evaluate_handle(self, _js):
        return self  # handle "на форму" — тот же фейк, evaluate() у него уже есть

    async def get_attribute(self, _attr):
        return "text"

    async def fill(self, _val):
        pass

    async def click(self):
        pass

    async def wait_for_load_state(self, _state, timeout=None):
        pass

    async def screenshot(self, path=None):
        pass


class _FakeManager:
    async def start(self):
        pass

    async def shutdown(self):
        pass

    def info(self, sid):
        return {"session_id": sid, "status": "open", "current_url": None}

    def get_page(self, sid):
        return _FakePage()

    def artifact_path(self, sid, name):
        return f"/tmp/test-{name}"

    async def render_pdf(self, html):
        return b"%PDF"


def test_submit_route_exists_and_reports_click_outcome():
    """Маршрут жив и возвращает исход клика. Вердикт `submitted` браузер-воркер
    не выставляет вовсе — он сообщает наблюдения, а порог доказательства держит
    finalize_confirmed слоем выше; поле остаётся на дефолте False."""
    app = create_app(manager=_FakeManager())
    with TestClient(app) as client:
        resp = client.post("/submit", json={
            "session_id": "s1",
            "fields": {"first_name": "Andrey"},
            "resume_path": None,
        })
    assert resp.status_code == 200
    body = resp.json()
    assert body["click_performed"] is True
    assert body["failure_signal"] is None
    assert body["submitted"] is False
    assert "example.com" in (body.get("confirmation_url") or "")


def test_submit_route_never_fabricates_proof_from_non_boolean_evaluate():
    """[SAFETY] _FakePage возвращает из evaluate строку "input". Сигналы
    доказательства сверяются строго (`is True`), поэтому истинная строка не
    должна превратиться в form_absent=True: доказательство собирается только из
    настоящих булевых наблюдений."""
    app = create_app(manager=_FakeManager())
    with TestClient(app) as client:
        resp = client.post("/submit", json={
            "session_id": "s1", "fields": {"first_name": "Andrey"}})
    body = resp.json()
    assert body["form_absent"] is False
    assert body["confirmation_signal"] is None
    assert "form_absent" in submission_proof_missing(SubmitResult(**body))


def test_submit_route_reports_not_submitted_when_field_unmatched():
    """Живой инцидент 23.07.2026: fill_form не смог найти/заполнить поле (locator
    не нашёлся) — submit_form НЕ должен жать кнопку и НЕ должен возвращать
    submitted=True поверх заведомо неполных данных."""

    class _MissingFieldPage(_FakePage):
        async def count(self):
            return 0  # ни один локатор не находится — все поля unmatched

    class _Manager(_FakeManager):
        def get_page(self, sid):
            return _MissingFieldPage()

    app = create_app(manager=_Manager())
    with TestClient(app) as client:
        resp = client.post("/submit", json={
            "session_id": "s1",
            "fields": {"custom_dropdown": "Yes"},
            "resume_path": None,
        })
    assert resp.status_code == 200
    body = resp.json()
    assert body["click_performed"] is False
    assert "custom_dropdown" in body["unmatched"]


def test_submit_route_reports_not_submitted_when_native_validation_blocks():
    """Живой инцидент 23.07.2026: поле, которое пайплайн намеренно не заполнял
    (work authorization/demographic — §3 НЕ авто), но сайт требует как HTML
    required — клик по submit срабатывает, но браузер сам блокирует отправку и
    подсвечивает поле :invalid. Это и есть корень бага: раньше клик == success."""

    class _InvalidAfterClickPage(_FakePage):
        invalid_count = 1

    class _Manager(_FakeManager):
        def get_page(self, sid):
            return _InvalidAfterClickPage()

    app = create_app(manager=_Manager())
    with TestClient(app) as client:
        resp = client.post("/submit", json={
            "session_id": "s1",
            "fields": {"first_name": "Andrey"},
            "resume_path": None,
        })
    assert resp.status_code == 200
    body = resp.json()
    assert body["failure_signal"] == "native_invalid"


def test_submit_route_404_on_unknown_session():
    class _NoSession:
        async def start(self): pass
        async def shutdown(self): pass
        def info(self, sid): return None  # session not found

    app = create_app(manager=_NoSession())
    with TestClient(app) as client:
        resp = client.post("/submit", json={"session_id": "bad", "fields": {}})
    assert resp.status_code == 404


@pytest.mark.browser
def test_submit_form_clicks_and_captures(tmp_path):
    """Real Chromium: fill a sample form, click submit, capture confirmation URL."""
    import asyncio

    from job_machine.browser.fill import submit_form
    from job_machine.browser.session import SessionManager

    async def run():
        mgr = SessionManager(headless=True, artifact_dir=str(tmp_path))
        await mgr.start()
        try:
            sid = await mgr.create_session()
            page = mgr.get_page(sid)
            # Load sample form from file URI
            fixture = (Path(__file__).parent.parent.parent / "src" / "job_machine" / "browser" / "fixtures" / "sample_form.html").resolve()
            await page.goto(f"file://{fixture}")
            shot = str(tmp_path / "confirm.png")
            # "full_name"/"email" — реальные обязательные поля fixture; до фикса
            # submitted=True было безусловным, так что и несуществующее "name", и
            # незаполненный required "email" маскировались.
            result = await submit_form(
                page, {"full_name": "Andrey", "email": "andrey@example.com"},
                screenshot_path=shot,
            )
            return result
        finally:
            await mgr.shutdown()

    result = asyncio.run(run())
    # Проверяется механика клика, а не доказательство подачи: фикстура никуда не
    # подтверждает, поэтому `submitted` (производное от полного доказательства)
    # здесь ложен по существу. Отсутствие failure_signal — это ровно "кнопка
    # нажата, валидация ничего не завалила".
    assert result.failure_signal is None
    assert result.click_performed is True
    assert result.screenshot_path is not None


@pytest.mark.browser
def test_submit_form_clicks_button_without_explicit_type(tmp_path):
    """Real Chromium: <button> with no type attribute defaults to submit per HTML
    spec (as on Ashby/Greenhouse React forms) — submit_form must still find and
    click it, not time out waiting for button[type='submit']."""
    import asyncio

    from job_machine.browser.fill import submit_form
    from job_machine.browser.session import SessionManager

    async def run():
        mgr = SessionManager(headless=True, artifact_dir=str(tmp_path))
        await mgr.start()
        try:
            sid = await mgr.create_session()
            page = mgr.get_page(sid)
            fixture = (
                Path(__file__).parent.parent.parent
                / "src" / "job_machine" / "browser" / "fixtures"
                / "sample_form_no_button_type.html"
            ).resolve()
            await page.goto(f"file://{fixture}")
            shot = str(tmp_path / "confirm.png")
            result = await submit_form(
                page,
                {"full_name": "Andrey", "email": "a@b.com"},
                screenshot_path=shot,
            )
            return result
        finally:
            await mgr.shutdown()

    result = asyncio.run(run())
    # Проверяется механика клика, а не доказательство подачи: фикстура никуда не
    # подтверждает, поэтому `submitted` (производное от полного доказательства)
    # здесь ложен по существу. Отсутствие failure_signal — это ровно "кнопка
    # нажата, валидация ничего не завалила".
    assert result.failure_signal is None
    assert result.click_performed is True
    assert result.screenshot_path is not None


@pytest.mark.browser
def test_submit_form_dismisses_generic_banner_without_clicking_form_controls(tmp_path):
    """Real Chromium: a non-OneTrust cookie banner overlaps a consent checkbox
    (not just the submit button), and the form has its own unrelated 'Decline to
    answer' control whose text overlaps cookie-banner vocabulary. submit_form must
    (1) still check the consent checkbox despite the overlay — the banner must be
    dismissed BEFORE fill_form runs, not only before the final click — and
    (2) never click the form's own decoy 'Decline' button while scanning for the
    cookie-banner's reject button."""
    import asyncio

    from job_machine.browser.fill import submit_form
    from job_machine.browser.session import SessionManager

    async def run():
        mgr = SessionManager(headless=True, artifact_dir=str(tmp_path))
        await mgr.start()
        try:
            sid = await mgr.create_session()
            page = mgr.get_page(sid)
            fixture = (
                Path(__file__).parent.parent.parent
                / "src" / "job_machine" / "browser" / "fixtures"
                / "sample_form_generic_cookie_banner.html"
            ).resolve()
            await page.goto(f"file://{fixture}")
            shot = str(tmp_path / "confirm.png")
            result = await submit_form(
                page, {"full_name": "Andrey"},
                consent_checks=["consent"], screenshot_path=shot,
            )
            decoy_clicked = await page.locator("#decline_demographic").get_attribute("data-clicked")
            return result, decoy_clicked
        finally:
            await mgr.shutdown()

    result, decoy_clicked = asyncio.run(run())
    assert result.failure_signal is None   # чекбокс согласия проставлен, клик прошёл
    assert decoy_clicked is None


@pytest.mark.browser
def test_submit_form_dismisses_onetrust_banner_before_clicking(tmp_path):
    """Real Chromium: a fixed-position OneTrust dark-filter overlay sits on top of
    the submit button (live incident 2026-07-17, Kaseya) — submit_form must reject
    the cookie banner first (privacy-preserving default) instead of timing out on
    a pointer-events-intercepted click."""
    import asyncio

    from job_machine.browser.fill import submit_form
    from job_machine.browser.session import SessionManager

    async def run():
        mgr = SessionManager(headless=True, artifact_dir=str(tmp_path))
        await mgr.start()
        try:
            sid = await mgr.create_session()
            page = mgr.get_page(sid)
            fixture = (
                Path(__file__).parent.parent.parent
                / "src" / "job_machine" / "browser" / "fixtures"
                / "sample_form_onetrust_banner.html"
            ).resolve()
            await page.goto(f"file://{fixture}")
            shot = str(tmp_path / "confirm.png")
            result = await submit_form(
                page, {"full_name": "Andrey"}, screenshot_path=shot,
            )
            return result
        finally:
            await mgr.shutdown()

    result = asyncio.run(run())
    # Проверяется механика клика, а не доказательство подачи: фикстура никуда не
    # подтверждает, поэтому `submitted` (производное от полного доказательства)
    # здесь ложен по существу. Отсутствие failure_signal — это ровно "кнопка
    # нажата, валидация ничего не завалила".
    assert result.failure_signal is None
    assert result.click_performed is True
    assert result.screenshot_path is not None


@pytest.mark.browser
def test_submit_form_reports_failure_when_field_locator_missing(tmp_path):
    """Real Chromium: `fields` references a name the form doesn't have (e.g. a
    react-select-style widget fill_form can't locate). submit_form must NOT click
    submit on known-incomplete data — confirms fill happens, then aborts before
    the click, and the page (and its URL) stays untouched."""
    import asyncio

    from job_machine.browser.fill import submit_form
    from job_machine.browser.session import SessionManager

    async def run():
        mgr = SessionManager(headless=True, artifact_dir=str(tmp_path))
        await mgr.start()
        try:
            sid = await mgr.create_session()
            page = mgr.get_page(sid)
            fixture = (
                Path(__file__).parent.parent.parent
                / "src" / "job_machine" / "browser" / "fixtures" / "sample_form.html"
            ).resolve()
            await page.goto(f"file://{fixture}")
            original_url = page.url  # нормализованный URL той же страницы
            shot = str(tmp_path / "confirm.png")
            result = await submit_form(
                page, {"full_name": "Andrey", "custom_widget_not_in_dom": "Yes"},
                screenshot_path=shot,
            )
            return result, page.url, original_url
        finally:
            await mgr.shutdown()

    result, final_url, original_url = asyncio.run(run())
    assert result.click_performed is False
    assert "custom_widget_not_in_dom" in result.unmatched
    assert final_url == original_url  # submit никогда не жали


@pytest.mark.browser
def test_submit_form_reports_failure_on_unanswered_required_field(tmp_path):
    """Real Chromium: a required field the pipeline correctly never auto-answers
    (work authorization — CLAUDE.md §3) is left empty by design. The click still
    fires (unmatched is empty — we simply never attempted this field), but the
    browser's own HTML5 constraint validation blocks the actual submission and
    marks the field :invalid — submit_form must report submitted=False, not just
    trust that a click happened. This shape (a still-visible required <select>
    under an unmoved Submit button) matches the screenshots sampled from the live
    incident 23.07.2026 — closes the native-required-field subclass of it; a
    fully custom (non-native) required widget with no HTML5 constraint API is a
    separate, tracked follow-up this test does not cover."""
    import asyncio

    from job_machine.browser.fill import submit_form
    from job_machine.browser.session import SessionManager

    async def run():
        mgr = SessionManager(headless=True, artifact_dir=str(tmp_path))
        await mgr.start()
        try:
            sid = await mgr.create_session()
            page = mgr.get_page(sid)
            fixture = (
                Path(__file__).parent.parent.parent
                / "src" / "job_machine" / "browser" / "fixtures"
                / "sample_form_unanswered_required_select.html"
            ).resolve()
            await page.goto(f"file://{fixture}")
            shot = str(tmp_path / "confirm.png")
            result = await submit_form(page, {"full_name": "Andrey"}, screenshot_path=shot)
            return result
        finally:
            await mgr.shutdown()

    result = asyncio.run(run())
    assert result.failure_signal == "native_invalid"
    assert result.screenshot_path is not None


@pytest.mark.browser
def test_submit_form_ignores_unrelated_invalid_field_outside_form(tmp_path):
    """Real Chromium: an unrelated, required-and-empty newsletter-signup widget
    sits OUTSIDE the application <form> on the same page. A document-wide :invalid
    check would find it and wrongly report the real (valid, complete) application
    submission as failed. The scoping fix (156cfbe) captures a handle to the
    submitted <form> before the click and checks :invalid only within it — this
    test is the regression guard for that scoping the code review flagged as
    untested."""
    import asyncio

    from job_machine.browser.fill import submit_form
    from job_machine.browser.session import SessionManager

    async def run():
        mgr = SessionManager(headless=True, artifact_dir=str(tmp_path))
        await mgr.start()
        try:
            sid = await mgr.create_session()
            page = mgr.get_page(sid)
            fixture = (
                Path(__file__).parent.parent.parent
                / "src" / "job_machine" / "browser" / "fixtures"
                / "sample_form_unrelated_invalid_widget.html"
            ).resolve()
            await page.goto(f"file://{fixture}")
            shot = str(tmp_path / "confirm.png")
            result = await submit_form(page, {"full_name": "Andrey"}, screenshot_path=shot)
            return result
        finally:
            await mgr.shutdown()

    result = asyncio.run(run())
    # Проверяется механика клика, а не доказательство подачи: фикстура никуда не
    # подтверждает, поэтому `submitted` (производное от полного доказательства)
    # здесь ложен по существу. Отсутствие failure_signal — это ровно "кнопка
    # нажата, валидация ничего не завалила".
    assert result.failure_signal is None
    assert result.click_performed is True
    assert result.screenshot_path is not None


@pytest.mark.browser
def test_submit_form_reports_failure_on_aria_invalid_custom_widget(tmp_path):
    """Real Chromium: a custom combobox widget (react-select-style, no native
    `required` attribute) is left empty because the pipeline correctly never
    auto-answers it (CLAUDE.md §3). The site's own JS blocks the submit and marks
    the widget aria-invalid="true" instead of relying on HTML5 constraint
    validation — :invalid alone never fires here. This markup mirrors a real,
    still-live Greenhouse posting (job-boards.eu.greenhouse.io/jetbrains, verified
    23.07.2026) and matches the shape sampled from a historical false-success
    screenshot (application submitted 2026-07-02) that :invalid-only detection
    does not catch — the tracked custom-widget gap from the review of 156cfbe."""
    import asyncio

    from job_machine.browser.fill import submit_form
    from job_machine.browser.session import SessionManager

    async def run():
        mgr = SessionManager(headless=True, artifact_dir=str(tmp_path))
        await mgr.start()
        try:
            sid = await mgr.create_session()
            page = mgr.get_page(sid)
            fixture = (
                Path(__file__).parent.parent.parent
                / "src" / "job_machine" / "browser" / "fixtures"
                / "sample_form_custom_widget_aria_invalid.html"
            ).resolve()
            await page.goto(f"file://{fixture}")
            shot = str(tmp_path / "confirm.png")
            result = await submit_form(page, {"full_name": "Andrey"}, screenshot_path=shot)
            return result
        finally:
            await mgr.shutdown()

    result = asyncio.run(run())
    assert result.screenshot_path is not None
    assert result.failure_signal == "aria_invalid"


@pytest.mark.browser
def test_submit_form_ignores_hidden_aria_invalid_widget(tmp_path):
    """Real Chromium: a leftover aria-invalid="true" element with display:none
    sits inside the submitted form (e.g. from an abandoned validation pass).
    _invalid_fields_signal excludes it via offsetParent !== null — this test is
    the regression guard for that visibility check (code review of caed66e noted
    it was implemented but never exercised by any fixture)."""
    import asyncio

    from job_machine.browser.fill import submit_form
    from job_machine.browser.session import SessionManager

    async def run():
        mgr = SessionManager(headless=True, artifact_dir=str(tmp_path))
        await mgr.start()
        try:
            sid = await mgr.create_session()
            page = mgr.get_page(sid)
            fixture = (
                Path(__file__).parent.parent.parent
                / "src" / "job_machine" / "browser" / "fixtures"
                / "sample_form_hidden_aria_invalid_widget.html"
            ).resolve()
            await page.goto(f"file://{fixture}")
            shot = str(tmp_path / "confirm.png")
            result = await submit_form(page, {"full_name": "Andrey"}, screenshot_path=shot)
            return result
        finally:
            await mgr.shutdown()

    result = asyncio.run(run())
    assert result.failure_signal is None
    assert result.click_performed is True


def _submit_fixture(fixture_name: str, fields: dict, tmp_path):
    """Прогнать submit_form по локальной фикстуре в реальном Chromium."""
    import asyncio

    from job_machine.browser.fill import submit_form
    from job_machine.browser.session import SessionManager

    async def run():
        mgr = SessionManager(headless=True, artifact_dir=str(tmp_path))
        await mgr.start()
        try:
            sid = await mgr.create_session()
            page = mgr.get_page(sid)
            fixture = (
                Path(__file__).parent.parent.parent
                / "src" / "job_machine" / "browser" / "fixtures" / fixture_name
            ).resolve()
            await page.goto(f"file://{fixture}")
            shot = str(tmp_path / "confirm.png")
            return await submit_form(page, fields, screenshot_path=shot)
        finally:
            await mgr.shutdown()

    return asyncio.run(run())


def _submit_intercepted(start_url: str, routes: dict, fields: dict, tmp_path):
    """Прогнать submit_form по СИНТЕТИЧЕСКОМУ адресу с перехватом сети.

    Нужен там, где важен хост (у file:// хоста нет). Ни один запрос не покидает
    процесс: page.route отвечает локальной строкой ДО сети, а домены — из
    зарезервированного RFC 2606 `.example`, который не резолвится в принципе.
    Реальные сайты работодателей не открываются.
    """
    import asyncio
    from urllib.parse import urlsplit

    from job_machine.browser.fill import submit_form
    from job_machine.browser.session import SessionManager

    async def run():
        mgr = SessionManager(headless=True, artifact_dir=str(tmp_path))
        await mgr.start()
        try:
            sid = await mgr.create_session()
            page = mgr.get_page(sid)

            async def handler(route):
                path = urlsplit(route.request.url).path
                await route.fulfill(status=200, content_type="text/html",
                                    body=routes.get(path, "<h1>not found</h1>"))

            await page.route("**/*", handler)
            await page.goto(start_url)
            shot = str(tmp_path / "confirm.png")
            return await submit_form(page, fields, screenshot_path=shot)
        finally:
            await mgr.shutdown()

    return asyncio.run(run())


def test_path_confirms_matches_tokens_not_substrings():
    """[SAFETY] Регрессия review 05.08.2026: маркеры подтверждения искались
    подстрокой по всему URL, включая хост и query — на реальных адресах
    крупнейших ATS это давало ложное подтверждение подачи."""
    from job_machine.browser.fill import _path_confirms

    assert _path_confirms("https://career5.successfactors.eu/careers") is False
    assert _path_confirms(
        "https://performancemanager.successfactors.eu/apply?error=1") is False
    assert _path_confirms(
        "https://appliedmaterials.wd1.myworkdayjobs.com/en-US/careers/"
        "job/R123/apply/error") is False
    assert _path_confirms(
        "https://company.example/login?next=%2Fapplication%2Fconfirmation") is False
    assert _path_confirms("https://boards.example/jobs/1/apply") is False

    # Настоящая страница подтверждения — токен именно в path:
    assert _path_confirms("https://boards.example/jobs/1/confirmation") is True
    assert _path_confirms("https://boards.example/application/submitted") is True
    assert _path_confirms("https://boards.example/thank-you") is True
    assert _path_confirms("https://boards.example/apply/success") is True


def test_affirmative_confirmation_rejects_denials_and_boilerplate():
    """Текст подтверждения должен утверждать факт подачи, а не отрицать его и не
    обещать его в будущем."""
    from job_machine.browser.fill import _affirmative_confirmation, _page_norm

    def check(raw):
        return _affirmative_confirmation(_page_norm(raw))

    assert check("Thank you for applying! Your application has been submitted.") is True
    assert check("We have received your application and will be in touch.") is True

    # Отрицание рядом с формулировкой успеха:
    assert check("Your application was NOT submitted. Please contact us.") is False
    # Апостроф съедается нормализацией: "couldn't process" обязан сойтись с
    # маркером "could not process" (review 05.08.2026 — этой щелью прошёл один
    # из воспроизведённых ложноположительных случаев):
    assert check("We couldn't process your application. "
                 "Thank you for applying.") is False
    assert check("Your application wasn't submitted.") is False
    assert check("Something went wrong. Thank you for applying, try again.") is False
    # Бойлерплейт «what happens next» здесь НЕ фильтруется: закрытый список
    # условных связок удалён как дырявый по построению ("as soon as", "in the
    # event that"). Обещание отсекается структурно — фраза засчитывается только
    # в видимом заголовке/статус-регионе, см.
    # test_submit_form_withholds_proof_on_career_landing_boilerplate.
    # Обычная форма без всякого подтверждения:
    assert check("Apply: Sample Role. Thank you for your interest in us.") is False


@pytest.mark.browser
def test_submit_form_produces_full_proof_on_confirmation_redirect(tmp_path):
    """Real Chromium: успешная отправка уводит на отдельную страницу
    подтверждения. Производитель доказательства (submit_form) обязан выдать ВСЕ
    пять сигналов — иначе finalize_confirmed не засчитает ни одну реальную
    подачу и каждая уйдёт в необратимый submit_unknown."""
    from job_machine.browser.schema import submission_proof_missing

    result = _submit_fixture(
        "submit_confirmation_redirect_form.html",
        {"full_name": "Andrey", "email": "andrey@example.com"}, tmp_path)

    assert submission_proof_missing(result) == []
    assert result.click_performed is True
    assert result.confirmation_signal == "confirmation_url"
    assert result.form_absent is True
    assert result.errors_absent is True
    assert result.screenshot_path is not None
    assert result.failure_signal is None


@pytest.mark.browser
def test_submit_form_produces_full_proof_on_inline_thank_you(tmp_path):
    """Real Chromium: React-форма (Greenhouse/Ashby) не перезагружает страницу —
    URL прежний, форма заменена благодарностью на месте. Подтверждение здесь
    честно устанавливается только по тексту."""
    from job_machine.browser.schema import submission_proof_missing

    result = _submit_fixture(
        "submit_inline_thank_you_form.html",
        {"full_name": "Andrey", "email": "andrey@example.com"}, tmp_path)

    assert submission_proof_missing(result) == []
    assert result.confirmation_signal == "thank_you_text"
    assert result.form_absent is True
    assert result.errors_absent is True


@pytest.mark.browser
def test_submit_form_confirms_by_text_when_url_says_nothing(tmp_path):
    """Real Chromium: настоящее подтверждение по неговорящему адресу (в path нет
    ни одного токена). Доказательство обязано собраться, а метка — быть
    "thank_you_text", а не "confirmation_url". Вместе с redirect-тестом выше это
    показывает, что метку различает именно path, а не порядок проверок."""
    from job_machine.browser.schema import submission_proof_missing

    result = _submit_fixture(
        "submit_plain_result_form.html",
        {"full_name": "Andrey", "email": "andrey@example.com"}, tmp_path)

    assert submission_proof_missing(result) == []
    assert result.confirmation_signal == "thank_you_text"


@pytest.mark.browser
def test_submit_form_confirms_despite_job_alerts_footer(tmp_path):
    """[SAFETY] Real Chromium, ложноОТРИЦАТЕЛЬНЫЙ разбор: честное подтверждение с
    типовым футером «Job alerts» / talent community, где стоит пустой
    `input type=email required`. У пустого required :invalid истинно ВСЕГДА, без
    всякой отправки, поэтому документ-широкая проверка ошибок уводила настоящую
    подачу в необратимый submit_unknown. Форма подписки не является формой
    подачи — ни ошибкой, ни оставшейся анкетой она считаться не должна."""
    from job_machine.browser.schema import submission_proof_missing

    result = _submit_fixture(
        "submit_job_alerts_footer_form.html",
        {"full_name": "Andrey", "email": "andrey@example.com"}, tmp_path)

    assert submission_proof_missing(result) == []
    assert result.errors_absent is True
    assert result.form_absent is True


@pytest.mark.browser
def test_submit_form_withholds_proof_when_form_rerendered_with_text_error(tmp_path):
    """[SAFETY] Real Chromium: сервер перерисовал ту же анкету по новому URL,
    ошибку нарисовал ОБЫЧНЫМ ТЕКСТОМ (ни :invalid, ни aria-invalid), а в шапке
    шаблона стоит «Thank you for applying». И якорь заголовка, и отсутствие
    невалидных контролов говорят «успех» — различить провал может только то, что
    форма подачи никуда не делась. Регрессия review 05.08.2026: в навигационной
    ветке form_absent означал всего лишь «адрес сменился»."""
    from job_machine.browser.schema import submission_proof_missing

    result = _submit_fixture(
        "submit_text_error_rerender_form.html", {"full_name": "Andrey"}, tmp_path)

    assert result.click_performed is True
    assert result.errors_absent is True     # ошибка текстовая — её тут не видно
    assert result.form_absent is False      # ...но анкета на экране
    assert result.confirmation_signal is None
    assert "form_absent" in submission_proof_missing(result)


@pytest.mark.browser
def test_submit_form_withholds_proof_on_career_landing_boilerplate(tmp_path):
    """[SAFETY] Real Chromium: клик увёл на карьерный лендинг с блоком «what
    happens next: as soon as we have received your application, a recruiter will
    be in touch». Формы нет, невалидных контролов нет, фраза есть — по одному
    лишь тексту это неотличимо от подтверждения. Оборот "as soon as" закрытым
    списком условных связок не ловится; ловит место фразы: обещание стоит в
    абзаце, подтверждение — в заголовке. Регрессия review 05.08.2026."""
    from job_machine.browser.schema import submission_proof_missing

    result = _submit_fixture(
        "submit_career_landing_form.html", {"full_name": "Andrey"}, tmp_path)

    assert result.click_performed is True
    assert result.form_absent is True       # формы на лендинге и правда нет
    assert result.errors_absent is True
    assert result.confirmation_signal is None   # ...но подтверждения тоже нет
    assert submission_proof_missing(result) == ["confirmation_signal"]


@pytest.mark.browser
def test_submit_form_withholds_proof_on_navigated_failure_page(tmp_path):
    """[SAFETY] Real Chromium, навигационная ветка: страница после клика прямо
    говорит «Your application was not submitted», формы там нет и невалидных
    контролов нет — то есть form_absent и errors_absent сами по себе выглядят
    «успешно». Доказательства быть не должно: различать успех и провал обязан
    текст, а не адрес."""
    from job_machine.browser.schema import submission_proof_missing

    result = _submit_fixture(
        "submit_failed_result_form.html", {"full_name": "Andrey"}, tmp_path)

    assert result.click_performed is True
    assert result.confirmation_signal is None
    assert "confirmation_signal" in submission_proof_missing(result)


@pytest.mark.browser
def test_submit_form_withholds_proof_when_navigated_page_rerenders_errors(tmp_path):
    """[SAFETY] Real Chromium, навигационная ветка: сервер ре-рендерит форму с
    ошибкой по НОВОМУ URL, где и путь содержит токен "confirmation", и текст
    благодарит. Прежний form_handle там мёртв, и «ошибок нет» по нему — артефакт
    уничтоженного контекста; проверять надо живой документ. Регрессия review
    05.08.2026."""
    from job_machine.browser.schema import submission_proof_missing

    result = _submit_fixture(
        "submit_rerendered_error_form.html", {"full_name": "Andrey"}, tmp_path)

    assert result.click_performed is True
    assert result.errors_absent is False   # видимый aria-invalid на живой странице
    assert "errors_absent" in submission_proof_missing(result)


_APPLICATION_FORM_HTML = (
    "<h1>Apply: Sample Role</h1>"
    "<form id='application' method='get' action='/apply/result'>"
    "<input name='full_name' value=''><input name='email' value=''>"
    "<button type='submit'>Submit Application</button></form>")


@pytest.mark.browser
def test_submit_form_ignores_hidden_confirmation_anchor(tmp_path):
    """[SAFETY] Real Chromium: благодарность спрятана тремя разными способами —
    display:none на [role=status], атрибут hidden на h2, visibility:hidden с
    aria-hidden на h3, — а видимый заголовок сообщает о провале. Скрытый якорь
    засчитываться не должен: прежний fallback innerText→textContent давал
    обратную асимметрию (скрытый текст не давал маркеров провала, но давал
    маркеры успеха). Регрессия review 05.08.2026."""
    from job_machine.browser.schema import submission_proof_missing

    hidden_thanks = (
        "<h1>Your session ended before we finished</h1>"
        "<div role='status' style='display:none'>Thank you for applying</div>"
        "<h2 hidden>Your application has been submitted</h2>"
        "<h3 style='visibility:hidden' aria-hidden='true'>Thanks for applying</h3>")
    result = _submit_intercepted(
        "https://boards.example/apply",
        {"/apply": _APPLICATION_FORM_HTML, "/apply/result": hidden_thanks},
        {"full_name": "Andrey"}, tmp_path)

    assert result.click_performed is True
    assert result.confirmation_signal is None
    assert "confirmation_signal" in submission_proof_missing(result)


@pytest.mark.browser
def test_submit_form_recognises_two_field_form_rerendered_by_name(tmp_path):
    """[SAFETY] Real Chromium: ре-рендер анкеты ИЗ ДВУХ ПОЛЕЙ, без file-input, с
    другими id и action — эвристика «похоже на анкету» её не узнавала и отдавала
    form_absent=True при целой анкете на экране. Подпись по именам полей узнаёт:
    сервер обязан их сохранить, иначе не восстановит введённые значения."""
    from job_machine.browser.schema import submission_proof_missing

    rerendered = (
        "<h1>Thank you for applying</h1>"
        "<p class='err'>Work authorization is a mandatory question.</p>"
        "<form id='application_v2' method='get' action='/apply/retry'>"
        "<input name='full_name' value='Andrey'><input name='email' value='a@b.c'>"
        "<button type='submit'>Submit Application</button></form>")
    result = _submit_intercepted(
        "https://boards.example/apply",
        {"/apply": _APPLICATION_FORM_HTML, "/apply/result": rerendered},
        {"full_name": "Andrey"}, tmp_path)

    assert result.click_performed is True
    assert result.errors_absent is True     # ошибка текстовая, её не видно
    assert result.form_absent is False      # ...но анкета на экране
    assert "form_absent" in submission_proof_missing(result)


@pytest.mark.browser
def test_submit_form_recognises_rerendered_form_with_react_button(tmp_path):
    """[SAFETY] Real Chromium: ре-рендер анкеты, где submit-контрол сделан в
    React-стиле `button type="button"` — прежняя эвристика требовала настоящей
    submit-кнопки и формы не узнавала. Подпись по именам полей от типа кнопки не
    зависит."""
    from job_machine.browser.schema import submission_proof_missing

    rerendered = (
        "<h1>Thank you for applying</h1>"
        "<p class='err'>Work authorization is a mandatory question.</p>"
        "<form id='application_v3' method='get' action='/apply/retry'>"
        "<input name='full_name' value='Andrey'><input name='email' value='a@b.c'>"
        "<button type='button'>Submit Application</button></form>")
    result = _submit_intercepted(
        "https://boards.example/apply",
        {"/apply": _APPLICATION_FORM_HTML, "/apply/result": rerendered},
        {"full_name": "Andrey"}, tmp_path)

    assert result.form_absent is False
    assert submission_proof_missing(result) != []


@pytest.mark.browser
def test_submit_form_withholds_proof_for_form_without_names_or_action(tmp_path):
    """[SAFETY] Real Chromium: React-идиом — форма с onSubmit и управляемыми
    инпутами, у которых есть только id: ни id у формы, ни action, ни имён. Такая
    подпись пуста и не совпадает НИ С ЧЕМ, поэтому форма, заведомо стоящая на
    экране, объявлялась исчезнувшей, и ре-рендер с текстовой ошибкой и
    благодарностью в заголовке собирал полное доказательство. Пустая подпись
    обязана трактоваться как «подписи нет». Регрессия review 05.08.2026."""
    from job_machine.browser.schema import submission_proof_missing

    react_form = (
        "<h1>Apply: Sample Role</h1>"
        "<form>"
        "<input id='full_name'><input id='email'>"
        "<button type='submit'>Submit Application</button></form>"
        "<script>document.querySelector('form').addEventListener('submit', e => {"
        "  e.preventDefault();"
        "  const h = document.createElement('h1');"
        "  h.textContent = 'Thank you for applying';"
        "  const p = document.createElement('p');"
        "  p.textContent = 'Work authorization is a mandatory question.';"
        "  document.body.prepend(p); document.body.prepend(h);"
        "});</script>")
    result = _submit_intercepted(
        "https://boards.example/apply", {"/apply": react_form},
        {"full_name": "Andrey"}, tmp_path)

    assert result.click_performed is True
    assert result.form_absent is False      # анкета на экране, доказывать нечем
    assert "form_absent" in submission_proof_missing(result)


@pytest.mark.browser
def test_submit_form_ignores_geometrically_hidden_anchor(tmp_path):
    """[SAFETY] Real Chromium: благодарность спрятана ГЕОМЕТРИЕЙ — пятью
    техниками визуально скрытого текста для скринридеров: обрезка в нулевой
    прямоугольник, вынос за левый край, нулевой кегль, отрицательный text-indent,
    clip-path. checkVisibility ни одну из них не видит. Бьёт это по role=status:
    визуально скрытая live-регион-озвучка штатна и часто не чистится после смены
    состояния, так что «объявили успех, потом сервер вернул ошибку» —
    правдоподобная последовательность. Регрессия review 05.08.2026."""
    from job_machine.browser.schema import submission_proof_missing

    sr_only = (
        "<h1>Your session ended, start over</h1>"
        "<div role='status' style='position:absolute;width:1px;height:1px;"
        "overflow:hidden;clip:rect(0 0 0 0)'>Thank you for applying</div>"
        "<h2 style='position:absolute;left:-9999px'>"
        "Your application has been submitted</h2>"
        "<h3 style='font-size:0'>Thanks for applying</h3>"
        "<h3 style='text-indent:-9999px;overflow:hidden;white-space:nowrap'>"
        "Thank you for your application</h3>"
        "<div role='alert' style='clip-path:inset(100%)'>"
        "Your application has been received</div>")
    result = _submit_intercepted(
        "https://boards.example/apply",
        {"/apply": _APPLICATION_FORM_HTML, "/apply/result": sr_only},
        {"full_name": "Andrey"}, tmp_path)

    assert result.click_performed is True
    assert result.confirmation_signal is None
    assert "confirmation_signal" in submission_proof_missing(result)


@pytest.mark.browser
def test_submit_form_withholds_proof_when_rerendered_form_changed_identity(tmp_path):
    """[SAFETY] Real Chromium: сервер сменил идентичность формы целиком — другой
    id, другой action, имена с префиксом. Совпадения нет ни по одному измерению,
    то есть «не нашёл свою форму» неотличимо от «формы нет». Консервативный
    откат: видимая неопознанная форма анкетного размера (submit-контрол плюс
    file-input либо >=5 контролов) делает отсутствие формы недоказуемым."""
    from job_machine.browser.schema import submission_proof_missing

    renamed = (
        "<h1>Thank you for applying</h1>"
        "<p class='err'>Work authorization is a mandatory question.</p>"
        "<form id='gh_app_v2' method='get' action='/apply/retry'>"
        "<input name='job_application[full_name]'><input name='job_application[email]'>"
        "<input name='job_application[phone]'><input name='job_application[city]'>"
        "<input name='job_application[resume]' type='file'>"
        "<button type='submit'>Submit Application</button></form>")
    result = _submit_intercepted(
        "https://boards.example/apply",
        {"/apply": _APPLICATION_FORM_HTML, "/apply/result": renamed},
        {"full_name": "Andrey"}, tmp_path)

    assert result.form_absent is False
    assert "form_absent" in submission_proof_missing(result)


@pytest.mark.browser
def test_submit_form_withholds_proof_on_already_applied_page(tmp_path):
    """[SAFETY] Real Chromium: «вы уже откликались» с благодарностью в шапке.
    Текущая попытка ничего не создала, доказательства подачи быть не должно."""
    from job_machine.browser.schema import submission_proof_missing

    duplicate = (
        "<h1>Thank you for applying</h1>"
        "<p>You have already applied to this position, this attempt was ignored.</p>")
    result = _submit_intercepted(
        "https://boards.example/apply",
        {"/apply": _APPLICATION_FORM_HTML, "/apply/result": duplicate},
        {"full_name": "Andrey"}, tmp_path)

    assert result.click_performed is True
    assert result.confirmation_signal is None
    assert submission_proof_missing(result) != []


@pytest.mark.browser
def test_submit_form_confirms_despite_job_search_header(tmp_path):
    """[SAFETY] Real Chromium, ложноОТРИЦАТЕЛЬНЫЙ разбор: честное подтверждение с
    шапочным поиском вакансий — два инпута, селект и submit-кнопка, причём поле
    поиска `required` и пустое. Эвристика «похоже на анкету» топила такую подачу
    в submit_unknown; по именам полей поиск с анкетой не совпадает никогда."""
    from job_machine.browser.schema import submission_proof_missing

    confirmation = (
        "<form id='job_search' method='get' action='/search'>"
        "<input name='keyword' required><input name='location'>"
        "<select name='department'><option>All</option></select>"
        "<button type='submit'>Search jobs</button></form>"
        "<h1>Thank you for applying</h1>"
        "<p>Your application has been submitted. We will be in touch.</p>")
    result = _submit_intercepted(
        "https://boards.example/apply",
        {"/apply": _APPLICATION_FORM_HTML, "/apply/result": confirmation},
        {"full_name": "Andrey"}, tmp_path)

    assert submission_proof_missing(result) == []
    assert result.errors_absent is True
    assert result.form_absent is True


@pytest.mark.browser
def test_submit_form_withholds_proof_when_host_contains_marker(tmp_path):
    """[SAFETY] Real Chromium (сеть перехвачена, .example-домен): страница ошибки
    на хосте career5.successfactors.example — подстрока "success" в ХОСТЕ и
    "apply"/"error" в path. Ровно тот ложноположительный случай, который ревью
    воспроизвело на SuccessFactors."""
    from job_machine.browser.schema import submission_proof_missing

    form = ("<h1>Apply</h1><form method='get' action='/apply/error'>"
            "<input id='full_name' name='full_name' required>"
            "<button type='submit'>Submit Application</button></form>")
    failed = ("<h1>Your application was not submitted</h1>"
              "<p>The session expired before we could process the form.</p>")
    result = _submit_intercepted(
        "https://career5.successfactors.example/careers/apply",
        {"/careers/apply": form, "/apply/error": failed},
        {"full_name": "Andrey"}, tmp_path)

    assert result.click_performed is True
    assert result.confirmation_signal is None
    assert submission_proof_missing(result) != []


@pytest.mark.browser
def test_submit_form_withholds_proof_when_query_contains_marker(tmp_path):
    """[SAFETY] Real Chromium (сеть перехвачена): редирект на логин с адресом
    возврата в query — company.example/login?next=%2Fapplication%2Fconfirmation.
    Типовое падение сессии ровно в момент отправки; "confirmation" живёт в query,
    подтверждением это не является."""
    from job_machine.browser.schema import submission_proof_missing

    form = ("<h1>Apply</h1><form method='get' action='/login'>"
            "<input id='full_name' name='full_name' required>"
            "<input type='hidden' name='next' value='/application/confirmation'>"
            "<button type='submit'>Submit Application</button></form>")
    login = "<h1>Sign in to continue</h1><form><input name='user'></form>"
    result = _submit_intercepted(
        "https://company.example/jobs/1/apply",
        {"/jobs/1/apply": form, "/login": login},
        {"full_name": "Andrey"}, tmp_path)

    assert result.confirmation_signal is None
    assert submission_proof_missing(result) != []


@pytest.mark.browser
def test_submit_form_withholds_proof_when_validation_fails(tmp_path):
    """Real Chromium, негатив: форма показала ошибку валидации (required-поле,
    которое пайплайн намеренно не заполняет — §3). Клик состоялся, но
    доказательства нет: errors_absent/form_absent/confirmation_signal должны
    остаться отрицательными. Ложноположительное доказательство здесь — это ровно
    инцидент 23.07.2026 (145+ фиктивных submitted)."""
    from job_machine.browser.schema import submission_proof_missing

    result = _submit_fixture(
        "sample_form_unanswered_required_select.html", {"full_name": "Andrey"}, tmp_path)

    assert result.click_performed is True     # клик — факт, он не зависит от исхода
    assert result.errors_absent is False
    assert result.form_absent is False
    assert result.confirmation_signal is None
    missing = submission_proof_missing(result)
    assert "errors_absent" in missing
    assert "confirmation_signal" in missing


@pytest.mark.browser
def test_submit_form_withholds_proof_on_aria_invalid_custom_widget(tmp_path):
    """Real Chromium, негатив №2: валидация целиком на JS (aria-invalid, без
    HTML5 constraint API) — доказательство тоже не должно собраться."""
    from job_machine.browser.schema import submission_proof_missing

    result = _submit_fixture(
        "sample_form_custom_widget_aria_invalid.html", {"full_name": "Andrey"}, tmp_path)

    assert result.click_performed is True
    assert result.errors_absent is False
    assert submission_proof_missing(result) != []


@pytest.mark.browser
def test_submit_form_reports_no_click_when_field_unmatched(tmp_path):
    """Ранний возврат (поле не сопоставлено, кнопку не жали) обязан отдавать
    осмысленные значения: click_performed=False и пустое доказательство."""
    from job_machine.browser.schema import submission_proof_missing

    result = _submit_fixture(
        "sample_form.html",
        {"full_name": "Andrey", "custom_widget_not_in_dom": "Yes"}, tmp_path)

    assert result.click_performed is False
    assert result.form_absent is False
    assert result.errors_absent is False
    assert result.confirmation_signal is None
    assert "click_performed" in submission_proof_missing(result)
