"""Тесты RecruiteeClient с httpx.MockTransport (без сетевых вызовов)."""

import httpx
import pytest

from job_machine.discovery.recruitee import RecruiteeClient

LIST_URL = "https://acme.recruitee.com/api/offers/"
DETAIL_URL = "https://acme.recruitee.com/api/offers/qa-lead"


def _client(handler) -> RecruiteeClient:
    http = httpx.Client(transport=httpx.MockTransport(handler))
    return RecruiteeClient(http_client=http, sleep=lambda *_: None)


def test_list_jobs_returns_raw_jobs():
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == LIST_URL
        return httpx.Response(200, json={"offers": [
            {"id": 1, "slug": "qa-lead", "title": "QA Lead",
             "careers_url": "https://acme.recruitee.com/o/qa-lead", "remote": True},
            {"id": 2, "slug": "pm", "title": "PM",
             "careers_url": "https://acme.recruitee.com/o/pm"},
        ]})

    c = _client(handler)
    jobs = c.list_jobs("acme")
    assert len(jobs) == 2
    assert jobs[0].slug == "qa-lead"
    assert jobs[0].remote is True
    assert jobs[1].remote is False


def test_list_jobs_returns_empty_list():
    c = _client(lambda r: httpx.Response(200, json={"offers": []}))
    assert c.list_jobs("acme") == []


def test_list_jobs_raises_on_404_account():
    c = _client(lambda r: httpx.Response(404, text="not found"))
    with pytest.raises(httpx.HTTPStatusError):
        c.list_jobs("ghost")


def test_list_jobs_raises_on_500():
    c = _client(lambda r: httpx.Response(500, text="error"))
    with pytest.raises(httpx.HTTPStatusError):
        c.list_jobs("acme")


def test_get_board_name_returns_none():
    c = _client(lambda r: httpx.Response(404))
    assert c.get_board_name("acme") is None


def test_check_job_live():
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == DETAIL_URL
        return httpx.Response(200, json={"offer": {"id": 1, "slug": "qa-lead"}})

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


def test_fetch_content_returns_description_from_offer_wrapper():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"offer": {"id": 1, "description": "<p>hi</p>"}})

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
