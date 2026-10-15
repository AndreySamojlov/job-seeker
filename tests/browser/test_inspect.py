import pytest

pytest.importorskip("playwright")

from job_machine.browser.blockers import classify_page
from job_machine.browser.inspect import (
    extract_form_schema,
    extract_signals,
    follow_apply_link_if_present,
    wait_for_fillable_content,
)

pytestmark = pytest.mark.browser


async def test_signals_on_clean_form_have_no_blocker(browser_manager, sample_form_url):
    sid = await browser_manager.create_session()
    page = browser_manager.get_page(sid)
    await page.goto(sample_form_url)
    signals = await extract_signals(page, http_status=200)
    assert signals["form_count"] == 1
    assert signals["has_login_form"] is False
    assert classify_page(signals) is None


async def test_invisible_recaptcha_is_not_a_blocker(
    browser_manager, invisible_recaptcha_form_url
):
    sid = await browser_manager.create_session()
    page = browser_manager.get_page(sid)
    await page.goto(invisible_recaptcha_form_url)
    signals = await extract_signals(page, http_status=200)
    assert signals["has_captcha"] is False
    assert classify_page(signals) is None


async def test_visible_recaptcha_checkbox_is_a_blocker(
    browser_manager, visible_recaptcha_form_url
):
    sid = await browser_manager.create_session()
    page = browser_manager.get_page(sid)
    await page.goto(visible_recaptcha_form_url)
    signals = await extract_signals(page, http_status=200)
    assert signals["has_captcha"] is True
    assert classify_page(signals) == "captcha"


async def test_hcaptcha_preloaded_hidden_challenge_is_not_a_blocker(
    browser_manager, hcaptcha_hidden_challenge_form_url
):
    sid = await browser_manager.create_session()
    page = browser_manager.get_page(sid)
    await page.goto(hcaptcha_hidden_challenge_form_url)
    signals = await extract_signals(page, http_status=200)
    assert signals["has_captcha"] is False
    assert classify_page(signals) is None


async def test_hcaptcha_visible_challenge_is_a_blocker(
    browser_manager, hcaptcha_visible_challenge_form_url
):
    sid = await browser_manager.create_session()
    page = browser_manager.get_page(sid)
    await page.goto(hcaptcha_visible_challenge_form_url)
    signals = await extract_signals(page, http_status=200)
    assert signals["has_captcha"] is True
    assert classify_page(signals) == "captcha"


async def test_real_field_count_on_formless_page(browser_manager, formless_fields_url):
    sid = await browser_manager.create_session()
    page = browser_manager.get_page(sid)
    await page.goto(formless_fields_url)
    signals = await extract_signals(page, http_status=200)
    assert signals["form_count"] == 0
    assert signals["real_field_count"] == 6
    assert classify_page(signals) is None


async def test_final_url_present_in_signals(browser_manager, sample_form_url):
    sid = await browser_manager.create_session()
    page = browser_manager.get_page(sid)
    await page.goto(sample_form_url)
    signals = await extract_signals(page, http_status=200)
    assert signals["final_url"] == sample_form_url


async def test_form_schema_extraction(browser_manager, sample_form_url):
    sid = await browser_manager.create_session()
    page = browser_manager.get_page(sid)
    await page.goto(sample_form_url)
    schema = await extract_form_schema(page)

    by_name = {f.name: f for f in schema.fields}
    assert by_name["full_name"].field_type == "text"
    assert by_name["full_name"].required is True
    assert by_name["email"].field_type == "email"
    assert by_name["location"].field_type == "select"
    assert by_name["location"].options == ["Remote", "Berlin", "Lisbon"]
    assert by_name["cover"].field_type == "textarea"
    assert schema.file_inputs == ["resume"]
    assert schema.consent_checkboxes == ["consent"]
    assert "Submit Application" in schema.submit_buttons


async def test_form_schema_submit_candidates_include_button_without_explicit_type(
    browser_manager, sample_form_no_button_type_url
):
    """<button> без type — тоже submit-кандидат (совпадает с локатором submit_form,
    fill.py), иначе disclosed-summary не покажет владельцу кнопку, которую реально
    кликнет submit_form."""
    sid = await browser_manager.create_session()
    page = browser_manager.get_page(sid)
    await page.goto(sample_form_no_button_type_url)
    schema = await extract_form_schema(page)

    assert "Submit Application" in schema.submit_buttons


async def test_group_label_extracted_from_label_before_fieldset(
    browser_manager, greenhouse_checkbox_consent_form_url
):
    sid = await browser_manager.create_session()
    page = browser_manager.get_page(sid)
    await page.goto(greenhouse_checkbox_consent_form_url)
    schema = await extract_form_schema(page)

    by_name = {f.name: f for f in schema.fields}
    pdn = by_name["job_application_answers_attributes_0_boolean_value"]
    assert pdn.group_label == "Point of Data Transfer"
    assert pdn.label == "Acknowledge/Confirm"  # per-option label unaffected

    relocate = by_name["job_application_answers_attributes_1_boolean_value"]
    assert relocate.group_label == "Are you willing to relocate?"


async def test_group_label_none_for_non_checkbox_fields(browser_manager, sample_form_url):
    sid = await browser_manager.create_session()
    page = browser_manager.get_page(sid)
    await page.goto(sample_form_url)
    schema = await extract_form_schema(page)

    by_name = {f.name: f for f in schema.fields}
    assert by_name["full_name"].group_label is None


# Два fieldset подряд, только у ПЕРВОГО есть непосредственно предшествующий <label>.
# Без границы на form-control узел, walk по previousElementSibling у второго
# fieldset перепрыгивает через первый fieldset (не LABEL, пропускается) и находит
# label первого вопроса — приписывая чужой group_label второму полю.
_TWO_FIELDSETS_ONE_LABEL_HTML = """
<form>
  <label>Q1</label>
  <fieldset id="q0">
    <input id="c0" name="q0" type="checkbox"><label for="c0">Yes</label>
  </fieldset>
  <fieldset id="q1">
    <input id="c1" name="q1" type="checkbox"><label for="c1">Yes</label>
  </fieldset>
</form>
"""


async def test_group_label_sibling_walk_stops_at_form_control_boundary(browser_manager):
    sid = await browser_manager.create_session()
    page = browser_manager.get_page(sid)
    await page.set_content(_TWO_FIELDSETS_ONE_LABEL_HTML)
    schema = await extract_form_schema(page)

    by_name = {f.name: f for f in schema.fields}
    assert by_name["q0"].group_label == "Q1"
    # q1 has no label of its own preceding it (only q0's fieldset does) — the
    # sibling walk must stop at q0's fieldset boundary, not reach past it to "Q1".
    assert by_name["q1"].group_label is None


# Fieldset с <legend> — own label ("I agree") отличается от legend, и нет ни
# предшествующего <label>-соседа, ни другого label внутри контейнера — так что
# любой корректный результат может прийти только из legend (strategy 1). Если
# strategy 1 сломать/убрать, это упадёт на None, а не молча пройдёт через strategy 2.
_LEGEND_FIELDSET_HTML = """
<form>
  <fieldset>
    <legend>Marketing consent</legend>
    <input id="c2" name="marketing" type="checkbox"><label for="c2">I agree</label>
  </fieldset>
</form>
"""


async def test_group_label_extracted_from_legend(browser_manager):
    sid = await browser_manager.create_session()
    page = browser_manager.get_page(sid)
    await page.set_content(_LEGEND_FIELDSET_HTML)
    schema = await extract_form_schema(page)

    by_name = {f.name: f for f in schema.fields}
    marketing = by_name["marketing"]
    assert marketing.group_label == "Marketing consent"
    assert marketing.label == "I agree"  # per-option label unaffected


# Голый <input> (без обёртки) как предшествующий sibling — не FIELDSET и не
# СОДЕРЖИТ form-control (querySelector ищет потомков, а у голого input их нет),
# так что без явной проверки САМОГО prev на form-control tag walk перепрыгнул бы
# через него к чужому label (code-review finding, 2026-07-15).
_BARE_INPUT_SIBLING_HTML = """
<form>
  <label for="x">Candidate Privacy Policy</label>
  <input id="x" type="text">
  <div class="field">
    <input id="m" name="marketing" type="checkbox"><label for="m">Send me offers</label>
  </div>
</form>
"""


async def test_group_label_sibling_walk_stops_at_bare_form_control(browser_manager):
    sid = await browser_manager.create_session()
    page = browser_manager.get_page(sid)
    await page.set_content(_BARE_INPUT_SIBLING_HTML)
    schema = await extract_form_schema(page)

    by_name = {f.name: f for f in schema.fields}
    # marketing's own preceding sibling is the bare <input id=x>, not a fieldset and
    # not a container OF a form control — the walk must still stop there, not reach
    # past it to "Candidate Privacy Policy" (an unrelated field's label).
    assert by_name["marketing"].group_label is None


# Секция-обёртка с классом "field", содержащая ДВА разных вопроса без per-question
# fieldset — closest() матчит секцию целиком (substring "field"). Без strategy 3
# (любой другой label в контейнере) это корректно возвращает None вместо того
# чтобы приписать marketing-чекбоксу label соседнего privacy-вопроса
# (code-review finding, 2026-07-15).
_SHARED_FIELD_SECTION_HTML = """
<form>
  <div class="application-fields">
    <label>Privacy Disclosure</label>
    <div>
      <input id="m" name="marketing_optin" type="checkbox"><label for="m">Send marketing emails</label>
    </div>
  </div>
</form>
"""


async def test_group_label_does_not_bleed_across_shared_field_section(browser_manager):
    sid = await browser_manager.create_session()
    page = browser_manager.get_page(sid)
    await page.set_content(_SHARED_FIELD_SECTION_HTML)
    schema = await extract_form_schema(page)

    by_name = {f.name: f for f in schema.fields}
    # No legend, no immediately-preceding sibling label (the "Privacy Disclosure"
    # label is INSIDE the shared container, not a sibling of it) — must be None,
    # not "Privacy Disclosure" bled in from the unrelated preceding question.
    assert by_name["marketing_optin"].group_label is None


async def test_follow_apply_link_navigates_to_form_page(
    browser_manager, two_step_apply_landing_url
):
    sid = await browser_manager.create_session()
    page = browser_manager.get_page(sid)
    await page.goto(two_step_apply_landing_url)
    signals_before = await extract_signals(page, http_status=200)
    assert signals_before["form_count"] == 0

    followed = await follow_apply_link_if_present(page)
    assert followed is True

    signals_after = await extract_signals(page, http_status=200)
    assert signals_after["form_count"] == 1
    assert classify_page(signals_after) is None


async def test_follow_apply_link_returns_false_when_no_apply_link(
    browser_manager, formless_fields_url
):
    sid = await browser_manager.create_session()
    page = browser_manager.get_page(sid)
    await page.goto(formless_fields_url)
    followed = await follow_apply_link_if_present(page)
    assert followed is False


async def test_follow_apply_link_skips_hrefless_decoy_button_before_real_link(
    browser_manager, two_step_apply_landing_with_decoy_button_url
):
    sid = await browser_manager.create_session()
    page = browser_manager.get_page(sid)
    await page.goto(two_step_apply_landing_with_decoy_button_url)
    signals_before = await extract_signals(page, http_status=200)
    assert signals_before["form_count"] == 0

    followed = await follow_apply_link_if_present(page)
    assert followed is True

    signals_after = await extract_signals(page, http_status=200)
    assert signals_after["form_count"] == 1
    assert classify_page(signals_after) is None


async def test_signals_immediately_after_domcontentloaded_miss_delayed_form(
    browser_manager, delayed_render_fields_url
):
    """Baseline проверка: без ожидания сигналы СРАЗУ после domcontentloaded не видят
    ещё не отрисованную форму (form_count и real_field_count оба 0)."""
    sid = await browser_manager.create_session()
    page = browser_manager.get_page(sid)
    await page.goto(delayed_render_fields_url, wait_until="domcontentloaded")
    signals = await extract_signals(page, http_status=200)
    assert signals["form_count"] == 0
    assert signals["real_field_count"] == 0


async def test_wait_for_fillable_content_catches_delayed_render(
    browser_manager, delayed_render_fields_url
):
    sid = await browser_manager.create_session()
    page = browser_manager.get_page(sid)
    await page.goto(delayed_render_fields_url, wait_until="domcontentloaded")

    await wait_for_fillable_content(page)

    signals = await extract_signals(page, http_status=200)
    assert signals["form_count"] == 1
    assert classify_page(signals) is None


async def test_wait_for_fillable_content_times_out_gracefully_when_nothing_appears(
    browser_manager,
):
    """Страница, где форма так и не появляется — функция не должна зависать/падать,
    просто вернуться по таймауту."""
    sid = await browser_manager.create_session()
    page = browser_manager.get_page(sid)
    await page.set_content("<html><body><p>No form here, ever.</p></body></html>")
    # Не должно кинуть исключение и не должно висеть заметно дольше timeout_ms.
    await wait_for_fillable_content(page, timeout_ms=500)


async def test_wait_for_function_is_blocked_by_strict_csp_without_unsafe_eval(
    browser_manager, csp_delayed_render_fields_url
):
    """Замок регрессии: подтверждает, что csp_delayed_render_fields_url действительно
    воспроизводит условия живого инцидента Ashby (2026-07-17) — строгий CSP
    script-src без 'unsafe-eval' ломает page.wait_for_function EvalError'ом. Если
    этот тест перестанет падать (исключение больше не бросается), значит фикстура
    больше не имитирует баг, и тест ниже (wait_for_fillable_content под той же CSP)
    больше не гарантирует защиту от регрессии на wait_for_function."""
    sid = await browser_manager.create_session()
    page = browser_manager.get_page(sid)
    await page.goto(csp_delayed_render_fields_url, wait_until="domcontentloaded")
    with pytest.raises(Exception):
        await page.wait_for_function("() => document.querySelector('form')", timeout=3000)


async def test_wait_for_fillable_content_catches_delayed_render_under_strict_csp(
    browser_manager, csp_delayed_render_fields_url
):
    """Регрессия живого инцидента Ashby (2026-07-17): wait_for_fillable_content должна
    дождаться формы даже под строгим CSP script-src без 'unsafe-eval', где
    page.wait_for_function ломается EvalError (см. тест выше) — wait_for_selector
    использует другой CDP-механизм (поиск по DOM-дереву, не JS-eval), CSP этому не
    подвержен."""
    sid = await browser_manager.create_session()
    page = browser_manager.get_page(sid)
    await page.goto(csp_delayed_render_fields_url, wait_until="domcontentloaded")

    await wait_for_fillable_content(page)

    signals = await extract_signals(page, http_status=200)
    assert signals["form_count"] == 1
    assert classify_page(signals) is None


async def test_react_select_required_shell_transfers_required_to_labelled_combobox(
    browser_manager, required_select_shell_form_url
):
    """Живой инцидент 2026-08-06: на job-boards.greenhouse.io обязательный вопрос
    расщеплён на пару элементов — лейблованный role=combobox (required=false) и
    безымянная заглушка React Select (required=true). Схема обязана отдать ОДНО
    поле: лейблованное И обязательное.

    Без сращивания требуемость доставалась безымянной половине, получала
    fallback-имя field_N и глушилась _AUTO_FIELD_RE в fill/adapter.py — гард
    mandatory_unknown не срабатывал, submit доходил до необратимого клика, и
    браузер блокировал отправку по :invalid (12 из 12 Greenhouse-заявок прогона
    06.08 ушли в submit_unknown/native_invalid)."""
    sid = await browser_manager.create_session()
    page = browser_manager.get_page(sid)
    await page.goto(required_select_shell_form_url)
    schema = await extract_form_schema(page)

    by_name = {f.name: f for f in schema.fields}
    question = by_name["question_27010971003"]
    assert question.required is True
    assert question.label == "How did you hear about Remote?*"

    # Безымянная половина не должна протекать в схему отдельным полем: именно она
    # и была невидимым для гарда обязательным полем.
    assert [f.name for f in schema.fields if f.name.startswith("field_")] == []
