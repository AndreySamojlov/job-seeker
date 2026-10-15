import httpx

from job_machine.discovery.landingjobs import LANDING_JOBS_LIST_URL, LandingJobsClient


def _client(handler) -> LandingJobsClient:
    http = httpx.Client(transport=httpx.MockTransport(handler))
    return LandingJobsClient(http_client=http)


def test_list_jobs_returns_flat_array():
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == LANDING_JOBS_LIST_URL
        return httpx.Response(200, json=[
            {"id": 1, "title": "QA Lead", "url": "https://landing.jobs/at/acme/qa-lead"},
        ])

    c = _client(handler)
    jobs = c.list_jobs("")
    assert len(jobs) == 1
    assert jobs[0].company_slug == "acme"


def test_get_board_name_returns_none():
    c = _client(lambda r: httpx.Response(200, json=[]))
    assert c.get_board_name("") is None


def test_check_job_live_and_gone():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[
            {"id": 1, "title": "QA Lead", "url": "https://landing.jobs/at/acme/qa-lead"},
        ])

    c = _client(handler)
    assert c.check_job("https://landing.jobs/at/acme/qa-lead") == "live"
    assert c.check_job("https://landing.jobs/at/acme/gone") == "gone"


def test_fetch_content_from_cache():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[
            {"id": 1, "title": "QA Lead", "url": "https://landing.jobs/at/acme/qa-lead",
             "role_description": "<p>hi</p>"},
        ])

    c = _client(handler)
    assert c.fetch_content("https://landing.jobs/at/acme/qa-lead") == "<p>hi</p>"
