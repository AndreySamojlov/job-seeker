"""Тесты HhClient — прямой httpx (без job-browser/Playwright, см. hh.py docstring)."""

import httpx

from job_machine.discovery.hh import HH_SEARCH_BASE, HhClient

_SEARCH_HTML = '''
<div data-qa="vacancy-serp__vacancy">
  <div id="1">
    <a data-qa="serp-item__title" href="https://hh.ru/vacancy/1">
      <span data-qa="serp-item__title-text">QA Lead</span>
    </a>
    <span data-qa="vacancy-label-work-schedule-remote">Можно удалённо</span>
    <a data-qa="vacancy-serp__vacancy-employer"><span data-qa="vacancy-serp__vacancy-employer-text">Acme</span></a>
    <span data-qa="vacancy-serp__vacancy-address">Кипр</span>
  </div>
</div>
'''

_VACANCY_LIVE_HTML = '<html><body><h1 data-qa="vacancy-title">QA Lead</h1></body></html>'
_VACANCY_404_HTML = '<html><body>Вакансия удалена или не найдена</body></html>'


def _client_with(responses: dict[str, str], status: int = 200) -> HhClient:
    """responses: full URL -> html body returned for a GET to that URL."""
    def handler(request: httpx.Request) -> httpx.Response:
        html = responses.get(str(request.url))
        if html is None:
            raise AssertionError(f"unexpected URL: {request.url}")
        return httpx.Response(status, text=html)

    http = httpx.Client(transport=httpx.MockTransport(handler))
    return HhClient(http_client=http)


def _client_with_status(status_code: int) -> HhClient:
    http = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(status_code, text="")))
    return HhClient(http_client=http)


def test_list_jobs_parses_search_page():
    url = f"{HH_SEARCH_BASE}?text=QA+Lead&area=1001&schedule=remote&order_by=publication_time"
    client = _client_with({url: _SEARCH_HTML})
    jobs = client.list_jobs("qa-lead", query={"text": "QA Lead", "area": "1001", "schedule": "remote"})
    assert len(jobs) == 1
    assert jobs[0].title == "QA Lead"
    assert jobs[0].company_name == "Acme"


def test_check_job_live_when_no_not_found_marker():
    client = _client_with({"https://hh.ru/vacancy/1": _VACANCY_LIVE_HTML})
    assert client.check_job("https://hh.ru/vacancy/1") == "live"


def test_check_job_gone_when_not_found_text_present():
    client = _client_with({"https://hh.ru/vacancy/1": _VACANCY_404_HTML})
    assert client.check_job("https://hh.ru/vacancy/1") == "gone"


def test_check_job_returns_error_on_http_5xx():
    client = _client_with_status(500)
    assert client.check_job("https://hh.ru/vacancy/1") == "error"


def test_get_board_name_is_none():
    client = _client_with({})
    assert client.get_board_name("qa-lead") is None


def test_list_jobs_percent_encodes_cyrillic_query_text():
    text = "Тестировщик"
    encoded = "%D0%A2%D0%B5%D1%81%D1%82%D0%B8%D1%80%D0%BE%D0%B2%D1%89%D0%B8%D0%BA"
    url = f"{HH_SEARCH_BASE}?text={encoded}&area=1001&schedule=remote&order_by=publication_time"
    client = _client_with({url: _SEARCH_HTML})
    jobs = client.list_jobs("qa-lead", query={"text": text, "area": "1001", "schedule": "remote"})
    assert len(jobs) == 1


def test_fetch_content_returns_html_for_live_page():
    client = _client_with({"https://hh.ru/vacancy/1": _VACANCY_LIVE_HTML})
    assert client.fetch_content("https://hh.ru/vacancy/1") == _VACANCY_LIVE_HTML


def test_fetch_content_returns_none_for_not_found_page():
    client = _client_with({"https://hh.ru/vacancy/1": _VACANCY_404_HTML})
    assert client.fetch_content("https://hh.ru/vacancy/1") is None


def test_constructs_with_no_args():
    client = HhClient()
    assert client is not None
    client.close()
