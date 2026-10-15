import pytest

pytestmark = pytest.mark.browser


async def test_readiness_checks_current_form_without_submit(browser_manager):
    from job_machine.browser.readiness import inspect_readiness
    sid = await browser_manager.create_session()
    page = browser_manager.get_page(sid)
    await page.set_content('<form onsubmit="window.submitted=true;return false">'
                           '<input required name="name"><button>Send</button></form>')
    assert not (await inspect_readiness(page))['ready']
    await page.locator('input').fill('Synthetic Applicant')
    assert (await inspect_readiness(page))['ready']
    assert not await page.evaluate('Boolean(window.submitted)')
    await page.locator('input').evaluate("e => e.setAttribute('aria-invalid','true')")
    assert not (await inspect_readiness(page))['ready']


async def test_readiness_rejects_ambiguous_and_custom_required(browser_manager):
    from job_machine.browser.readiness import inspect_readiness
    sid = await browser_manager.create_session()
    page = browser_manager.get_page(sid)
    await page.set_content('<form><input value="x"><div role="combobox" aria-required="true"></div>'
                           '<button>Send</button></form>')
    assert not (await inspect_readiness(page))['ready']


async def test_readiness_http_preserves_page_and_reports_missing_session(browser_manager):
    import httpx
    from job_machine.browser.app import create_app
    app = create_app(browser_manager)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            sid = (await client.post('/session')).json()['session_id']
            page = browser_manager.get_page(sid)
            await page.set_content('<form><input value="synthetic"><button>Send</button></form>')
            response = await client.get(f'/session/{sid}/readiness')
            assert response.status_code == 200
            assert response.json()['ready'] is True
            assert await page.locator('input').input_value() == 'synthetic'
            assert (await client.get('/session/missing/readiness')).status_code == 404
    from job_machine.browser.readiness import inspect_readiness
    await page.set_content('<form><input value="x"><button>Send</button></form>' * 2)
    assert not (await inspect_readiness(page))['ready']


async def test_aria_required_checkbox_cannot_pass_unchecked(browser_manager):
    from job_machine.browser.readiness import inspect_readiness
    sid = await browser_manager.create_session()
    page = browser_manager.get_page(sid)
    await page.set_content('<form><input type="checkbox" aria-required="true"><button>Send</button></form>')
    assert not (await inspect_readiness(page))['ready']
