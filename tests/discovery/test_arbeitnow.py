"""Тесты ArbeitnowClient с httpx.MockTransport (без сетевых вызовов)."""

import httpx
import pytest

from job_machine.discovery.arbeitnow import ARBEITNOW_LIST_URL, ArbeitnowClient


def _client(handler) -> ArbeitnowClient:
    http = httpx.Client(transport=httpx.MockTransport(handler))
    return ArbeitnowClient(http_client=http, sleep=lambda *_: None)


def test_list_jobs_single_page():
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url).startswith(ARBEITNOW_LIST_URL)
        return httpx.Response(200, json={
            "data": [
                {"slug": "a", "title": "QA Lead", "url": "https://www.arbeitnow.com/jobs/x/a",
                 "company_name": "Acme", "remote": True},
            ],
            "links": {"next": None},
        })

    c = _client(handler)
    jobs = c.list_jobs("")
    assert len(jobs) == 1
    assert jobs[0].title == "QA Lead"


def test_list_jobs_follows_pagination():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if len(calls) == 1:
            return httpx.Response(200, json={
                "data": [{"slug": "p1", "title": "Page1", "url": "https://www.arbeitnow.com/jobs/x/p1"}],
                "links": {"next": "https://www.arbeitnow.com/api/job-board-api?page=2"},
            })
        return httpx.Response(200, json={
            "data": [{"slug": "p2", "title": "Page2", "url": "https://www.arbeitnow.com/jobs/x/p2"}],
            "links": {"next": None},
        })

    c = _client(handler)
    jobs = c.list_jobs("")
    assert [j.title for j in jobs] == ["Page1", "Page2"]
    assert len(calls) == 2


def test_list_jobs_stops_at_max_pages_safety_cap():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "data": [{"slug": "x", "title": "X", "url": "https://www.arbeitnow.com/jobs/x/x"}],
            "links": {"next": "https://www.arbeitnow.com/api/job-board-api?page=999"},
        })

    c = _client(handler)
    jobs = c.list_jobs("")
    assert len(jobs) == ArbeitnowClient.MAX_PAGES


def test_get_board_name_returns_none():
    c = _client(lambda r: httpx.Response(200, json={"data": [], "links": {}}))
    assert c.get_board_name("") is None


def test_check_job_live_when_url_in_cache():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "data": [{"slug": "a", "title": "A", "url": "https://www.arbeitnow.com/jobs/x/a"}],
            "links": {"next": None},
        })

    c = _client(handler)
    assert c.check_job("https://www.arbeitnow.com/jobs/x/a") == "live"


def test_check_job_gone_when_url_not_in_cache():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "data": [{"slug": "a", "title": "A", "url": "https://www.arbeitnow.com/jobs/x/a"}],
            "links": {"next": None},
        })

    c = _client(handler)
    assert c.check_job("https://www.arbeitnow.com/jobs/x/gone") == "gone"


def test_check_job_uses_cache_only_once():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(200, json={
            "data": [{"slug": "a", "title": "A", "url": "https://www.arbeitnow.com/jobs/x/a"}],
            "links": {"next": None},
        })

    c = _client(handler)
    c.check_job("https://www.arbeitnow.com/jobs/x/a")
    c.check_job("https://www.arbeitnow.com/jobs/x/a")
    c.fetch_content("https://www.arbeitnow.com/jobs/x/a")
    assert len(calls) == 1  # один list_jobs на весь инстанс, не на каждый вызов


def test_check_job_error_on_network():
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("timeout", request=req)

    c = _client(handler)
    assert c.check_job("https://www.arbeitnow.com/jobs/x/a") == "error"


def test_fetch_content_returns_cached_description():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "data": [{"slug": "a", "title": "A", "url": "https://www.arbeitnow.com/jobs/x/a",
                      "description": "<p>hi</p>"}],
            "links": {"next": None},
        })

    c = _client(handler)
    assert c.fetch_content("https://www.arbeitnow.com/jobs/x/a") == "<p>hi</p>"


def test_fetch_content_none_when_not_found():
    c = _client(lambda r: httpx.Response(200, json={"data": [], "links": {}}))
    assert c.fetch_content("https://www.arbeitnow.com/jobs/x/gone") is None
