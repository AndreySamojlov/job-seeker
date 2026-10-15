"""Тесты LeverClient с httpx.MockTransport (без сетевых вызовов)."""

import httpx
import pytest

from job_machine.discovery.lever import LeverClient, LEVER_BASE, LEVER_BASE_EU


def _make_transport(routes: dict) -> httpx.MockTransport:
    """routes: {url: (status, body_dict|list|str)}"""

    def handler(request: httpx.Request) -> httpx.Response:
        url_str = str(request.url.copy_with(params={}))
        if url_str in routes:
            status, body = routes[url_str]
            if isinstance(body, (dict, list)):
                return httpx.Response(status, json=body)
            return httpx.Response(status, text=str(body))
        return httpx.Response(404, text="not found")

    return httpx.MockTransport(handler)


def _client(routes: dict) -> LeverClient:
    transport = _make_transport(routes)
    http = httpx.Client(transport=transport)
    return LeverClient(http_client=http)


BOARD_URL = f"{LEVER_BASE}/netflix"
JOB_URL = "https://jobs.lever.co/netflix/job-abc"


def test_list_jobs_returns_raw_jobs():
    routes = {
        BOARD_URL: (200, [
            {"id": "j1", "text": "Backend Eng",
             "hostedUrl": "https://jobs.lever.co/netflix/j1",
             "categories": {"location": "Remote", "team": "Eng", "commitment": "Full-time"}},
            {"id": "j2", "text": "Data Scientist",
             "hostedUrl": "https://jobs.lever.co/netflix/j2"},
        ]),
    }
    c = _client(routes)
    jobs = c.list_jobs("netflix")
    assert len(jobs) == 2
    assert jobs[0].id == "j1"
    assert jobs[0].title == "Backend Eng"
    assert jobs[0].location == "Remote"
    assert jobs[1].location is None


def test_list_jobs_returns_empty_on_empty_array():
    routes = {BOARD_URL: (200, [])}
    c = _client(routes)
    assert c.list_jobs("netflix") == []


def test_list_jobs_raises_on_500():
    routes = {BOARD_URL: (500, "error")}
    c = _client(routes)
    with pytest.raises(httpx.HTTPStatusError):
        c.list_jobs("netflix")


def test_get_board_name_returns_none():
    c = _client({})
    assert c.get_board_name("netflix") is None


def test_check_job_live():
    routes = {JOB_URL: (200, {"id": "job-abc"})}
    c = _client(routes)
    assert c.check_job(JOB_URL) == "live"


def test_check_job_gone():
    routes = {}  # → 404
    c = _client(routes)
    assert c.check_job(JOB_URL) == "gone"


def test_check_job_error_on_5xx():
    routes = {JOB_URL: (503, "unavailable")}
    c = _client(routes)
    assert c.check_job(JOB_URL) == "error"


def test_check_job_error_on_network():
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("timeout", request=req)

    http = httpx.Client(transport=httpx.MockTransport(handler))
    c = LeverClient(http_client=http)
    assert c.check_job(JOB_URL) == "error"


def test_fetch_content_returns_description_plain():
    routes = {JOB_URL: (200, {"id": "job-abc", "descriptionPlain": "hello"})}
    c = _client(routes)
    assert c.fetch_content(JOB_URL) == "hello"


def test_fetch_content_none_on_404():
    routes = {}  # → 404
    c = _client(routes)
    assert c.fetch_content(JOB_URL) is None


def test_fetch_content_raises_on_5xx():
    routes = {JOB_URL: (503, "unavailable")}
    c = _client(routes)
    with pytest.raises(httpx.HTTPStatusError):
        c.fetch_content(JOB_URL)


def test_fetch_content_raises_on_network_error():
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("timeout", request=req)

    http = httpx.Client(transport=httpx.MockTransport(handler))
    c = LeverClient(http_client=http)
    with pytest.raises(httpx.HTTPError):
        c.fetch_content(JOB_URL)


# EU data-residency борды (api.eu.lever.co) 404-ят на глобальном api.lever.co —
# найдено при пробе Quadcode/XM Group/CoinsPaid (sourcing-ru-en-remote). Клиент
# должен транспарентно повторить запрос на EU-хосте прежде чем считать мёртвым.

EU_BOARD_URL = f"{LEVER_BASE_EU}/quadcode"
API_JOB_URL_GLOBAL = f"{LEVER_BASE}/quadcode/job-1"
API_JOB_URL_EU = f"{LEVER_BASE_EU}/quadcode/job-1"


def test_list_jobs_falls_back_to_eu_host_on_404():
    routes = {
        EU_BOARD_URL: (200, [
            {"id": "j1", "text": "QA Lead", "hostedUrl": "https://jobs.eu.lever.co/quadcode/j1"},
        ]),
        # GLOBAL board URL нарочно отсутствует в routes -> 404 по умолчанию
    }
    c = _client(routes)
    jobs = c.list_jobs("quadcode")
    assert len(jobs) == 1
    assert jobs[0].title == "QA Lead"


def test_list_jobs_raises_when_both_hosts_404():
    c = _client({})
    with pytest.raises(httpx.HTTPStatusError):
        c.list_jobs("ghost-token")


def test_check_job_falls_back_to_eu_host():
    routes = {API_JOB_URL_EU: (200, {"id": "job-1"})}
    c = _client(routes)
    assert c.check_job(API_JOB_URL_GLOBAL) == "live"


def test_check_job_gone_when_both_hosts_404():
    c = _client({})
    assert c.check_job(API_JOB_URL_GLOBAL) == "gone"


def test_fetch_content_falls_back_to_eu_host():
    routes = {API_JOB_URL_EU: (200, {"id": "job-1", "descriptionPlain": "eu hello"})}
    c = _client(routes)
    assert c.fetch_content(API_JOB_URL_GLOBAL) == "eu hello"


def test_fetch_content_none_when_both_hosts_404():
    c = _client({})
    assert c.fetch_content(API_JOB_URL_GLOBAL) is None
