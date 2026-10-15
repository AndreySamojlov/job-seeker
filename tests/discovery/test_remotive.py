import httpx

from job_machine.discovery.remotive import REMOTIVE_LIST_URL, RemotiveClient


def _client(handler) -> RemotiveClient:
    http = httpx.Client(transport=httpx.MockTransport(handler))
    return RemotiveClient(http_client=http)


def test_list_jobs_returns_raw_jobs():
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url).startswith(REMOTIVE_LIST_URL)
        return httpx.Response(200, json={"jobs": [
            {"id": 1, "url": "https://remotive.com/remote-jobs/qa/1", "title": "QA Lead",
             "company_name": "Acme"},
        ]})

    c = _client(handler)
    jobs = c.list_jobs("")
    assert len(jobs) == 1


def test_get_board_name_returns_none():
    c = _client(lambda r: httpx.Response(200, json={"jobs": []}))
    assert c.get_board_name("") is None


def test_check_job_live_and_gone():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"jobs": [
            {"id": 1, "url": "https://remotive.com/remote-jobs/qa/1", "title": "QA Lead"},
        ]})

    c = _client(handler)
    assert c.check_job("https://remotive.com/remote-jobs/qa/1") == "live"
    assert c.check_job("https://remotive.com/remote-jobs/qa/gone") == "gone"


def test_fetch_content_from_cache():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"jobs": [
            {"id": 1, "url": "https://remotive.com/remote-jobs/qa/1", "title": "QA Lead",
             "description": "<p>hi</p>"},
        ]})

    c = _client(handler)
    assert c.fetch_content("https://remotive.com/remote-jobs/qa/1") == "<p>hi</p>"
