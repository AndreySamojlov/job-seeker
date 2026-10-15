import pytest
from playwright.async_api import async_playwright

from job_machine.browser.fill import fill_form

_HTML = """
<form>
  <label for="c0">Remote, Germany</label><input id="c0" name="q[]" type="checkbox">
  <label for="c1">Berlin, Germany</label><input id="c1" name="q[]" type="checkbox">
  <label for="c2">Warsaw, Poland</label><input id="c2" name="q[]" type="checkbox">
</form>
"""


@pytest.mark.browser
async def test_fill_checks_matching_option_in_group(tmp_path):
    async with async_playwright() as p:
        b = await p.chromium.launch()
        page = await b.new_page()
        await page.set_content(_HTML)
        res = await fill_form(page, {"q[]": "Remote, Germany"})
        assert "q[]" in res.filled
        assert await page.locator("#c0").is_checked() is True
        assert await page.locator("#c1").is_checked() is False
        assert await page.locator("#c2").is_checked() is False
        await b.close()


@pytest.mark.browser
async def test_fill_checkbox_no_match_goes_unmatched(tmp_path):
    async with async_playwright() as p:
        b = await p.chromium.launch()
        page = await b.new_page()
        await page.set_content(_HTML)
        res = await fill_form(page, {"q[]": "Nowhere"})
        assert "q[]" in res.unmatched
        for cid in ("#c0", "#c1", "#c2"):
            assert await page.locator(cid).is_checked() is False
        await b.close()


# Структура Greenhouse: <fieldset id="q[]"> оборачивает input'ы с name="q[]".
# Раньше _locator(...).first цеплял fieldset (по id) → loc.fill() на fieldset → 500.
_GH_HTML = """
<form>
  <fieldset id="q[]" class="checkbox" aria-required="true">
    <input id="c0" name="q[]" type="checkbox"><label for="c0">Remote, Germany</label>
    <input id="c1" name="q[]" type="checkbox"><label for="c1">Berlin, Germany</label>
  </fieldset>
</form>
"""


@pytest.mark.browser
async def test_fill_group_wrapped_in_fieldset_with_same_id(tmp_path):
    async with async_playwright() as p:
        b = await p.chromium.launch()
        page = await b.new_page()
        await page.set_content(_GH_HTML)
        res = await fill_form(page, {"q[]": "Remote, Germany"})
        assert "q[]" in res.filled
        assert await page.locator("#c0").is_checked() is True
        assert await page.locator("#c1").is_checked() is False
        await b.close()


@pytest.mark.browser
async def test_truthy_value_does_not_force_first(tmp_path):
    from playwright.async_api import async_playwright
    from job_machine.browser.fill import fill_form
    html = '<form><label for="c0">Remote, Germany</label><input id="c0" name="q[]" type="checkbox"></form>'
    async with async_playwright() as p:
        b = await p.chromium.launch(); page = await b.new_page()
        await page.set_content(html)
        res = await fill_form(page, {"q[]": "yes"})
        assert "q[]" in res.unmatched
        assert await page.locator("#c0").is_checked() is False
        await b.close()
