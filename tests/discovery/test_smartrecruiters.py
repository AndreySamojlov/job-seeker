"""Тесты SmartRecruitersClient с httpx.MockTransport (без сетевых вызовов)."""

import httpx
import pytest

from job_machine.discovery.smartrecruiters import SMARTRECRUITERS_BASE, SmartRecruitersClient

LIST_URL = f"{SMARTRECRUITERS_BASE}/acme/postings"
DETAIL_URL = f"{SMARTRECRUITERS_BASE}/acme/postings/12345"


def _client(handler) -> SmartRecruitersClient:
    http = httpx.Client(transport=httpx.MockTransport(handler))
    return SmartRecruitersClient(http_client=http, sleep=lambda *_: None)


def test_list_jobs_single_page():
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url).startswith(LIST_URL)
        return httpx.Response(200, json={
            "totalFound": 2,
            "content": [
                {"id": "1", "name": "QA Engineer",
                 "location": {"city": "Kyiv", "country": "ua", "hybrid": True}},
                {"id": "2", "name": "PM", "location": {"remote": True}},
            ],
        })

    c = _client(handler)
    jobs = c.list_jobs("acme")
    assert len(jobs) == 2
    assert jobs[0].id == "1"
    assert jobs[0].title == "QA Engineer"


def test_list_jobs_follows_offset_pagination():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(dict(request.url.params))
        if len(calls) == 1:
            return httpx.Response(200, json={
                "totalFound": 2, "content": [{"id": "1", "name": "First", "location": {}}],
            })
        return httpx.Response(200, json={
            "totalFound": 2, "content": [{"id": "2", "name": "Second", "location": {}}],
        })

    c = _client(handler)
    jobs = c.list_jobs("acme")
    assert [j.title for j in jobs] == ["First", "Second"]
    assert len(calls) == 2
    assert calls[0]["offset"] == "0"
    assert calls[1]["offset"] == "1"


def test_list_jobs_stops_at_max_pages_safety_cap():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "totalFound": 100000, "content": [{"id": "1", "name": "X", "location": {}}],
        })

    c = _client(handler)
    jobs = c.list_jobs("acme")
    assert len(jobs) == SmartRecruitersClient.MAX_PAGES


def test_list_jobs_empty_content_stops_pagination():
    c = _client(lambda r: httpx.Response(200, json={"totalFound": 5, "content": []}))
    assert c.list_jobs("acme") == []


def test_list_jobs_raises_on_missing_total_found():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"content": [{"id": "1", "name": "X", "location": {}}]})

    c = _client(handler)
    with pytest.raises(KeyError):
        c.list_jobs("acme")


def test_list_jobs_raises_on_404_account():
    c = _client(lambda r: httpx.Response(404, text="not found"))
    with pytest.raises(httpx.HTTPStatusError):
        c.list_jobs("ghost")


def test_get_board_name_returns_none():
    c = _client(lambda r: httpx.Response(404))
    assert c.get_board_name("acme") is None


def test_check_job_live():
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == DETAIL_URL
        return httpx.Response(200, json={"id": "12345"})

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


def test_fetch_content_concatenates_sections_in_order():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "id": "12345",
            "jobAd": {"sections": {
                "qualifications": {"title": "Qual", "text": "<p>3 years</p>"},
                "companyDescription": {"title": "Company", "text": "<p>About us</p>"},
                "jobDescription": {"title": "Role", "text": "<p>Do QA</p>"},
            }},
        })

    c = _client(handler)
    content = c.fetch_content(DETAIL_URL)
    assert content == "<p>About us</p>\n<p>Do QA</p>\n<p>3 years</p>"


def test_fetch_content_none_when_no_sections():
    c = _client(lambda r: httpx.Response(200, json={"id": "12345", "jobAd": {"sections": {}}}))
    assert c.fetch_content(DETAIL_URL) is None


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
