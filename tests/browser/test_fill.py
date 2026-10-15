from pathlib import Path

import pytest

pytest.importorskip("playwright")

from job_machine.browser.fill import fill_form

pytestmark = pytest.mark.browser


def test_css_attr_prefix_escapes_quotes_and_backslashes():
    from job_machine.browser.fill import _css_attr_prefix

    assert _css_attr_prefix("id", "react-select-foo-option-") == (
        '[id^="react-select-foo-option-"]'
    )
    assert _css_attr_prefix("id", 'weird"name') == '[id^="weird\\"name"]'


async def test_fill_sets_values_attaches_resume_and_stops(
    browser_manager, sample_form_url, tmp_path
):
    sid = await browser_manager.create_session()
    page = browser_manager.get_page(sid)
    await page.goto(sample_form_url)
    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"%PDF-1.4 test resume")
    shot = str(tmp_path / "fill.png")

    result = await fill_form(
        page,
        {"full_name": "Andrey Samoylov", "email": "a@b.com", "consent": "true"},
        resume_path=str(resume),
        screenshot_path=shot,
    )

    assert "full_name" in result.filled
    assert result.resume_attached is True
    assert result.stopped_before_submit is True
    assert await page.input_value("#full_name") == "Andrey Samoylov"
    # §3 fix: truthy-fallback убран — consent без точного label-совпадения не тикается
    assert await page.is_checked("#consent") is False
    assert "consent" in result.unmatched
    # форма НЕ отправлена: остались на той же странице, submit на месте
    assert page.url == sample_form_url
    assert await page.locator("button[type='submit']").count() == 1
    assert Path(shot).exists()


async def test_fill_handles_bracketed_greenhouse_names(
    browser_manager, greenhouse_form_url, tmp_path
):
    sid = await browser_manager.create_session()
    page = browser_manager.get_page(sid)
    await page.goto(greenhouse_form_url)
    shot = str(tmp_path / "gh.png")

    result = await fill_form(
        page,
        {
            "job_application[first_name]": "Andrey",
            "job_application[email]": "a@b.com",
            "job_application[answers_attributes][0][text_value]": "1 month",
        },
        screenshot_path=shot,
    )

    assert "job_application[first_name]" in result.filled
    assert "job_application[answers_attributes][0][text_value]" in result.filled
    assert (
        await page.input_value("[name='job_application[answers_attributes][0][text_value]']")
        == "1 month"
    )
    assert result.stopped_before_submit is True
    assert page.url == greenhouse_form_url


async def test_fill_select_falls_back_and_reports_unmatched(
    browser_manager, greenhouse_form_url, tmp_path
):
    sid = await browser_manager.create_session()
    page = browser_manager.get_page(sid)
    await page.goto(greenhouse_form_url)

    result = await fill_form(
        page,
        {
            "job_application[answers_attributes][1]": "absolutely-no-such-option",
        },
        screenshot_path=str(tmp_path / "s.png"),
    )

    assert "job_application[answers_attributes][1]" in result.unmatched
    assert result.stopped_before_submit is True


def test_fill_core_path_never_clicks_or_presses():
    import inspect as _inspect

    import job_machine.browser.fill as fill_mod

    # Инвариант безопасности: ЯДРО fill-пути (text/select/checkbox) ничего не
    # кликает, не жмёт клавиш и не вызывает submit — значит не может отправить
    # форму. react-select-ветка — отдельный, более узкий инвариант ниже
    # (owner-approval 2026-07-23, см. docs/superpowers/specs/
    # 2026-07-23-geo-autocomplete-fill-design.md).
    #
    # _normalized_match включён СЮДА (а не только в combobox-кортеж ниже), т.к.
    # это общий предикат, вызываемый И _select_robust (ядро), И
    # _match_and_click_option (combobox, вне этого теста) — часть ядра тоже
    # обязана удовлетворять самому строгому применимому инварианту (zero
    # tolerance), а не только более мягкому combobox-исключению.
    fill_path = (
        fill_mod.fill_form,
        fill_mod._locator,
        fill_mod._css_attr,
        fill_mod._norm,
        fill_mod._select_robust,
        fill_mod._normalized_match,
    )
    src = "\n".join(_inspect.getsource(fn) for fn in fill_path)
    for forbidden in (
        ".click(",
        ".press(",
        ".dispatch_event(",
        ".tap(",
        "keyboard",
        "submit(",
        "requestSubmit",
        "e.form",
    ):
        assert forbidden not in src, f"путь fill_form (ядро) не должен содержать {forbidden!r}"


def test_combobox_path_never_submits_or_presses_navigation_keys():
    import inspect as _inspect

    import job_machine.browser.fill as fill_mod

    # react-select-ветка (owner-approval 2026-07-23) вправе .click() (открыть
    # меню/выбрать опцию) и press_sequentially() (набрать значение для
    # debounced-поиска) — это единственное узкое исключение из инварианта выше.
    # Но submit-смежные пути и Enter/Tab (которые в некоторых виджетах триггерят
    # submit/навигацию) остаются под запретом.
    #
    # _normalized_match включён — общий предикат с ядром (см. комментарий выше),
    # проверяется здесь же на узкий denylist (он и так пуст от чего-либо
    # подозрительного — чистая строковая функция).
    #
    # Денилист НЕ включает "\n"/"\r" как литеральные подстроки исходника:
    # _fill_react_select_combobox сама содержит их в строке санитизации
    # `value.replace("\r", " ").replace("\n", " ")` (security-fix review
    # 2026-07-24) — это КОД ЗАЩИТЫ, а не нарушение. Более того, такая проверка
    # структурно не могла бы поймать реальную регрессию (удаление санитизации
    # убрало бы "\n" из исходника и тест ложно прошёл бы), так что она не даёт
    # genuine defense-in-depth — только гарантированный false positive против
    # уже прошедшего ревью кода.
    combobox_path = (
        fill_mod._fill_react_select_combobox,
        fill_mod._match_and_click_option,
        fill_mod._wait_for_options,
        fill_mod._option_locator,
        fill_mod._css_attr_prefix,
        fill_mod._normalized_match,
    )
    src = "\n".join(_inspect.getsource(fn) for fn in combobox_path)
    for forbidden in (
        ".dispatch_event(",
        ".tap(",
        "keyboard.press(",
        "submit(",
        "requestSubmit",
        "e.form",
        '"Enter"',
        "'Enter'",
        '"Tab"',
        "'Tab'",
    ):
        assert forbidden not in src, f"react-select-путь не должен содержать {forbidden!r}"


async def test_fill_static_combobox_selects_by_click(
    browser_manager, static_combobox_form_url, tmp_path
):
    sid = await browser_manager.create_session()
    page = browser_manager.get_page(sid)
    await page.goto(static_combobox_form_url)

    result = await fill_form(page, {"preferred-language": "Portuguese"})

    assert "preferred-language" in result.filled
    assert await page.locator("#preferred-language").get_attribute("data-selected") == "Portuguese"
    assert result.stopped_before_submit is True


async def test_fill_geo_autocomplete_types_and_selects_debounced_option(
    browser_manager, debounced_geo_autocomplete_form_url, tmp_path
):
    sid = await browser_manager.create_session()
    page = browser_manager.get_page(sid)
    await page.goto(debounced_geo_autocomplete_form_url)

    result = await fill_form(page, {"candidate-location": "Lisbon, Portugal"})

    assert "candidate-location" in result.filled
    assert (
        await page.locator("#candidate-location").get_attribute("data-selected")
        == "Lisbon, Portugal"
    )
    assert result.stopped_before_submit is True
    # Доказательство посимвольного ввода (press_sequentially), а не одного batch .fill():
    # несколько input-событий подряд — иначе тест не ловит регрессию к .fill().
    input_events = await page.locator("#candidate-location").get_attribute("data-input-events")
    assert int(input_events) > 1


async def test_fill_geo_autocomplete_no_match_marks_unmatched(
    browser_manager, debounced_geo_autocomplete_form_url, tmp_path, monkeypatch
):
    import job_machine.browser.fill as fill_mod

    monkeypatch.setattr(fill_mod, "_COMBOBOX_SEARCH_TIMEOUT_MS", 500)

    sid = await browser_manager.create_session()
    page = browser_manager.get_page(sid)
    await page.goto(debounced_geo_autocomplete_form_url)

    result = await fill_form(page, {"candidate-location": "Nowhere City"})

    assert "candidate-location" in result.unmatched
    assert await page.locator("#candidate-location").get_attribute("data-selected") is None


async def test_fill_combobox_sanitizes_newline_before_typing(
    browser_manager, debounced_geo_autocomplete_form_url, tmp_path
):
    """Поведенческое доказательство санитизации (замена статического
    source-text денилиста "\\n" из test_combobox_path_never_submits_or_presses_
    navigation_keys — он не мог отличить код-защиту от кода-бага, см. коммит
    выше). Живой инцидент риска: literal \\n/\\r в значении react-select-поля,
    попав в press_sequentially НЕсанитизированным, Playwright интерпретирует
    как настоящую клавишу Enter — а поле сидит в реальной <form> рядом с
    submit-кнопкой, так что Enter мог бы неявно отправить форму.

    ВАЖНО: используется debounced-фикстура (geo-autocomplete), не статичная
    (static_combobox_form_url) — на статичной опции рендерятся синхронно на
    click, поэтому _fill_react_select_combobox возвращается через
    _match_and_click_option ДО того, как код доходит до press_sequentially,
    и тест на static-фикстуре прошёл бы даже с реверченной санитизацией
    (ложноотрицательный, проверено вручную в ходе разработки). На debounced-
    фикстуре меню пустое сразу после click — код обязан дойти до
    press_sequentially, значит только там тест реально нагружает защиту.
    """
    sid = await browser_manager.create_session()
    page = browser_manager.get_page(sid)
    await page.goto(debounced_geo_autocomplete_form_url)

    # Само по себе значение не обязано матчить опцию (CITIES = ["Lisbon,
    # Portugal", "Berlin, Germany"]) — важен только факт, что embedded \n
    # никогда не доходит до реального keydown.
    result = await fill_form(page, {"candidate-location": "Lisbon\nGermany"})

    assert result.stopped_before_submit is True
    assert page.url == debounced_geo_autocomplete_form_url  # навигации не было
    assert await page.locator("form").count() == 1  # форма на месте, не отправлена
    assert await page.locator("button[type='submit']").count() == 1
