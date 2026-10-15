"""Тесты WorkableClient с httpx.MockTransport (без сетевых вызовов)."""

import httpx
import pytest

from job_machine.discovery.workable import (
    WORKABLE_DETAIL_BASE, WORKABLE_LIST_BASE, WorkableClient,
)

LIST_URL = f"{WORKABLE_LIST_BASE}/acme/jobs"
DETAIL_URL = f"{WORKABLE_DETAIL_BASE}/acme/jobs/ABC123"


def _client(handler) -> WorkableClient:
    http = httpx.Client(transport=httpx.MockTransport(handler))
    return WorkableClient(http_client=http, sleep=lambda *_: None)


def test_list_jobs_single_page():
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == LIST_URL
        return httpx.Response(200, json={
            "total": 2,
            "results": [
                {"id": 1, "shortcode": "A1", "title": "QA Lead", "remote": True},
                {"id": 2, "shortcode": "A2", "title": "PM", "remote": False},
            ],
        })

    c = _client(handler)
    jobs = c.list_jobs("acme")
    assert len(jobs) == 2
    assert jobs[0].shortcode == "A1"
    assert jobs[0].title == "QA Lead"


def test_list_jobs_follows_pagination_via_next_page_token():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.content)
        if len(calls) == 1:
            return httpx.Response(200, json={
                "total": 2, "results": [{"id": 1, "shortcode": "A1", "title": "Page1"}],
                "nextPage": "opaque-token-xyz",
            })
        return httpx.Response(200, json={
            "total": 2, "results": [{"id": 2, "shortcode": "A2", "title": "Page2"}],
        })

    c = _client(handler)
    jobs = c.list_jobs("acme")
    assert [j.title for j in jobs] == ["Page1", "Page2"]
    assert len(calls) == 2
    import json as _json
    assert _json.loads(calls[1]) == {"token": "opaque-token-xyz"}


def test_list_jobs_stops_at_max_pages_safety_cap():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "total": 10000, "results": [{"id": 1, "shortcode": "A1", "title": "X"}],
            "nextPage": "always-more",
        })

    c = _client(handler)
    jobs = c.list_jobs("acme")
    assert len(jobs) == WorkableClient.MAX_PAGES  # не должно уйти в бесконечный цикл


def test_list_jobs_raises_on_404_account():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="not found")

    c = _client(handler)
    with pytest.raises(httpx.HTTPStatusError):
        c.list_jobs("ghost")


def test_get_board_name_returns_none():
    c = _client(lambda r: httpx.Response(404))
    assert c.get_board_name("acme") is None


def test_check_job_live():
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == DETAIL_URL
        return httpx.Response(200, json={"shortcode": "ABC123"})

    c = _client(handler)
    assert c.check_job(DETAIL_URL) == "live"


def test_check_job_gone():
    c = _client(lambda r: httpx.Response(404))
    assert c.check_job(DETAIL_URL) == "gone"


def test_check_job_error_on_5xx():
    c = _client(lambda r: httpx.Response(503, text="unavailable"))
    assert c.check_job(DETAIL_URL) == "error"


def test_check_job_error_on_network():
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("timeout", request=req)

    c = _client(handler)
    assert c.check_job(DETAIL_URL) == "error"


def test_fetch_content_returns_description():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"shortcode": "ABC123", "description": "<p>hi</p>"})

    c = _client(handler)
    assert c.fetch_content(DETAIL_URL) == "<p>hi</p>"


def test_fetch_content_none_on_404():
    c = _client(lambda r: httpx.Response(404))
    assert c.fetch_content(DETAIL_URL) is None


def test_fetch_content_raises_on_5xx():
    c = _client(lambda r: httpx.Response(503, text="unavailable"))
    with pytest.raises(httpx.HTTPStatusError):
        c.fetch_content(DETAIL_URL)


def test_fetch_content_raises_on_network_error():
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("timeout", request=req)

    c = _client(handler)
    with pytest.raises(httpx.HTTPError):
        c.fetch_content(DETAIL_URL)
