import httpx

from job_machine.discovery.himalayas import HIMALAYAS_LIST_URL, HimalayasClient


def _client(handler) -> HimalayasClient:
    http = httpx.Client(transport=httpx.MockTransport(handler))
    return HimalayasClient(http_client=http)


def test_list_jobs_returns_raw_jobs():
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url).startswith(HIMALAYAS_LIST_URL)
        return httpx.Response(200, json={"jobs": [
            {"title": "QA Lead", "applicationLink": "https://himalayas.app/companies/a/jobs/qa",
             "companyName": "Acme"},
        ], "totalCount": 1})

    c = _client(handler)
    jobs = c.list_jobs("")
    assert len(jobs) == 1


def test_get_board_name_returns_none():
    c = _client(lambda r: httpx.Response(200, json={"jobs": [], "totalCount": 0}))
    assert c.get_board_name("") is None


def test_check_job_live_and_gone():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"jobs": [
            {"title": "QA Lead", "applicationLink": "https://himalayas.app/companies/a/jobs/qa"},
        ], "totalCount": 1})

    c = _client(handler)
    assert c.check_job("https://himalayas.app/companies/a/jobs/qa") == "live"
    assert c.check_job("https://himalayas.app/companies/a/jobs/gone") == "gone"


def test_fetch_content_returns_excerpt_not_full_text():
    """Himalayas list-ответ несёт только excerpt (короткий), не полный текст —
    это задокументированное ограничение источника (шапка плана), не баг."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"jobs": [
            {"title": "QA Lead", "applicationLink": "https://himalayas.app/companies/a/jobs/qa",
             "excerpt": "short blurb"},
        ], "totalCount": 1})

    c = _client(handler)
    assert c.fetch_content("https://himalayas.app/companies/a/jobs/qa") == "short blurb"
