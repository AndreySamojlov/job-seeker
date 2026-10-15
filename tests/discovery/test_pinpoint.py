"""Тесты PinpointClient с httpx.MockTransport (без сетевых вызовов)."""

import httpx
import pytest

from job_machine.discovery.pinpoint import PinpointClient

LIST_URL = "https://acme.pinpointhq.com/postings.json"
JOB_URL = "https://acme.pinpointhq.com/en/postings/uuid-here"


def _client(handler) -> PinpointClient:
    http = httpx.Client(transport=httpx.MockTransport(handler))
    return PinpointClient(http_client=http, sleep=lambda *_: None)


def test_list_jobs_returns_raw_jobs():
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == LIST_URL
        return httpx.Response(200, json={"data": [
            {"id": 1, "title": "QA Engineer", "url": JOB_URL,
             "description": "<p>hi</p>", "location": {"name": "Remote"},
             "workplace_type": "remote"},
            {"id": 2, "title": "PM", "url": "https://acme.pinpointhq.com/en/postings/pm",
             "location": {"city": "Berlin"}},
        ]})

    c = _client(handler)
    jobs = c.list_jobs("acme")
    assert len(jobs) == 2
    assert jobs[0].id == "1"
    assert jobs[0].description == "<p>hi</p>"
    assert jobs[1].location_name == "Berlin"


def test_list_jobs_returns_empty_list():
    c = _client(lambda r: httpx.Response(200, json={"data": []}))
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
        assert str(request.url) == JOB_URL
        return httpx.Response(200, text="<html>job</html>")

    c = _client(handler)
    assert c.check_job(JOB_URL) == "live"


def test_check_job_gone():
    c = _client(lambda r: httpx.Response(404))
    assert c.check_job(JOB_URL) == "gone"


def test_check_job_error_on_5xx():
    c = _client(lambda r: httpx.Response(503, text="unavailable"))
    assert c.check_job(JOB_URL) == "error"


def test_check_job_error_on_network():
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("timeout", request=req)

    c = _client(handler)
    assert c.check_job(JOB_URL) == "error"


def test_fetch_content_matches_by_url_in_relisted_board():
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == LIST_URL
        return httpx.Response(200, json={"data": [
            {"id": 1, "title": "QA Engineer", "url": JOB_URL, "description": "<p>hi</p>"},
            {"id": 2, "title": "PM", "url": "https://acme.pinpointhq.com/en/postings/pm",
             "description": "<p>other</p>"},
        ]})

    c = _client(handler)
    assert c.fetch_content(JOB_URL) == "<p>hi</p>"


def test_fetch_content_none_when_url_not_in_board():
    c = _client(lambda r: httpx.Response(200, json={"data": []}))
    assert c.fetch_content(JOB_URL) is None


def test_fetch_content_none_on_404():
    c = _client(lambda r: httpx.Response(404))
    assert c.fetch_content(JOB_URL) is None


def test_fetch_content_raises_on_5xx():
    c = _client(lambda r: httpx.Response(503, text="unavailable"))
    with pytest.raises(httpx.HTTPStatusError):
        c.fetch_content(JOB_URL)


def test_fetch_content_raises_on_network_error():
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("timeout", request=req)

    c = _client(handler)
    with pytest.raises(httpx.HTTPError):
        c.fetch_content(JOB_URL)
