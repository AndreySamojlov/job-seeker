import httpx

from job_machine.discovery.jobicy import JOBICY_LIST_URL, JobicyClient


def _client(handler) -> JobicyClient:
    http = httpx.Client(transport=httpx.MockTransport(handler))
    return JobicyClient(http_client=http)


def test_list_jobs_returns_raw_jobs():
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url).startswith(JOBICY_LIST_URL)
        return httpx.Response(200, json={"jobs": [
            {"id": 1, "url": "https://jobicy.com/jobs/1-qa", "jobTitle": "QA Lead",
             "companyName": "Acme"},
        ]})

    c = _client(handler)
    jobs = c.list_jobs("")
    assert len(jobs) == 1
    assert jobs[0].job_title == "QA Lead"


def test_list_jobs_empty():
    c = _client(lambda r: httpx.Response(200, json={"jobs": []}))
    assert c.list_jobs("") == []


def test_get_board_name_returns_none():
    c = _client(lambda r: httpx.Response(200, json={"jobs": []}))
    assert c.get_board_name("") is None


def test_check_job_live_and_gone():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"jobs": [
            {"id": 1, "url": "https://jobicy.com/jobs/1-qa", "jobTitle": "QA Lead"},
        ]})

    c = _client(handler)
    assert c.check_job("https://jobicy.com/jobs/1-qa") == "live"
    assert c.check_job("https://jobicy.com/jobs/2-gone") == "gone"


def test_check_job_error_on_network():
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("timeout", request=req)

    c = _client(handler)
    assert c.check_job("https://jobicy.com/jobs/1-qa") == "error"


def test_fetch_content_from_cache():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"jobs": [
            {"id": 1, "url": "https://jobicy.com/jobs/1-qa", "jobTitle": "QA Lead",
             "jobDescription": "<p>hi</p>"},
        ]})

    c = _client(handler)
    assert c.fetch_content("https://jobicy.com/jobs/1-qa") == "<p>hi</p>"
    assert c.fetch_content("https://jobicy.com/jobs/2-gone") is None
