"""Тесты AshbyClient с httpx.MockTransport (без сетевых вызовов)."""

import json

import httpx
import pytest

from job_machine.discovery.ashby import AshbyClient, ASHBY_BASE


def _make_transport(routes: dict) -> httpx.MockTransport:
    """routes: {url: (status, body_dict|str)}"""

    def handler(request: httpx.Request) -> httpx.Response:
        # Убираем query-параметры для матчинга
        url_str = str(request.url.copy_with(params={}))
        if url_str in routes:
            status, body = routes[url_str]
            if isinstance(body, (dict, list)):
                return httpx.Response(status, json=body)
            return httpx.Response(status, text=str(body))
        return httpx.Response(404, text="not found")

    return httpx.MockTransport(handler)


def _client(routes: dict) -> AshbyClient:
    transport = _make_transport(routes)
    http = httpx.Client(transport=transport)
    return AshbyClient(http_client=http)


BOARD_URL = f"{ASHBY_BASE}/ramp"
JOB_URL = f"{BOARD_URL}/job-123"


def test_list_jobs_returns_raw_jobs():
    routes = {
        BOARD_URL: (200, {
            "name": "Ramp",
            "jobs": [
                {"id": "j1", "title": "Backend Eng",
                 "jobUrl": "https://jobs.ashbyhq.com/ramp/j1",
                 "workplaceType": "Remote"},
                {"id": "j2", "title": "Data Eng",
                 "jobUrl": "https://jobs.ashbyhq.com/ramp/j2"},
            ],
        }),
    }
    c = _client(routes)
    jobs = c.list_jobs("ramp")
    assert len(jobs) == 2
    assert jobs[0].id == "j1"
    assert jobs[0].title == "Backend Eng"
    assert jobs[0].workplace_type == "Remote"


def test_list_jobs_returns_empty_without_jobs_key():
    routes = {BOARD_URL: (200, {"name": "Ramp"})}
    c = _client(routes)
    assert c.list_jobs("ramp") == []


def test_list_jobs_returns_empty_on_404():
    routes = {}  # всё → 404
    c = _client(routes)
    assert c.list_jobs("ramp") == []


def test_get_board_name_returns_name():
    routes = {BOARD_URL: (200, {"name": "Ramp Financial", "jobs": []})}
    c = _client(routes)
    assert c.get_board_name("ramp") == "Ramp Financial"


def test_get_board_name_returns_none_on_404():
    routes = {}
    c = _client(routes)
    assert c.get_board_name("ramp") is None


def test_get_board_name_raises_on_500():
    routes = {BOARD_URL: (500, "internal error")}
    c = _client(routes)
    with pytest.raises(httpx.HTTPStatusError):
        c.get_board_name("ramp")


def test_list_jobs_raises_on_500():
    routes = {BOARD_URL: (500, "internal error")}
    c = _client(routes)
    with pytest.raises(httpx.HTTPStatusError):
        c.list_jobs("ramp")


# Ashby публичный posting-api НЕ имеет per-job GET-эндпоинта (всегда 401 —
# подтверждено прямым запросом к продакшн-API). Единственный публичный источник
# истины — board-level листинг (уже используемый list_jobs/get_board_name), который
# содержит все живые вакансии целиком, включая descriptionHtml. check_job/fetch_content
# поэтому рефетчат доску и ищут job_id в её jobs[], а не бьют по source_url напрямую.


def test_check_job_live_when_job_present_on_board():
    routes = {
        BOARD_URL: (200, {"name": "Ramp", "jobs": [{"id": "job-123", "title": "X"}]}),
    }
    c = _client(routes)
    assert c.check_job(JOB_URL) == "live"


def test_check_job_gone_when_job_absent_from_board():
    routes = {
        BOARD_URL: (200, {"name": "Ramp", "jobs": [{"id": "other-job", "title": "X"}]}),
    }
    c = _client(routes)
    assert c.check_job(JOB_URL) == "gone"


def test_check_job_gone_when_board_missing():
    routes = {}  # board itself → 404
    c = _client(routes)
    assert c.check_job(JOB_URL) == "gone"


def test_check_job_error_on_5xx():
    routes = {BOARD_URL: (503, "unavailable")}
    c = _client(routes)
    assert c.check_job(JOB_URL) == "error"


def test_check_job_error_on_network():
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("timeout", request=req)

    http = httpx.Client(transport=httpx.MockTransport(handler))
    c = AshbyClient(http_client=http)
    assert c.check_job(JOB_URL) == "error"


def test_check_job_error_on_malformed_url():
    c = _client({})
    assert c.check_job("https://example.com/not-ashby") == "error"


def test_fetch_content_returns_description_html_from_board_listing():
    routes = {
        BOARD_URL: (200, {"name": "Ramp", "jobs": [
            {"id": "job-123", "descriptionHtml": "<p>hi</p>"},
        ]}),
    }
    c = _client(routes)
    assert c.fetch_content(JOB_URL) == "<p>hi</p>"


def test_fetch_content_falls_back_to_description_plain():
    routes = {
        BOARD_URL: (200, {"name": "Ramp", "jobs": [
            {"id": "job-123", "descriptionPlain": "hi plain"},
        ]}),
    }
    c = _client(routes)
    assert c.fetch_content(JOB_URL) == "hi plain"


def test_fetch_content_none_when_job_absent_from_board():
    routes = {
        BOARD_URL: (200, {"name": "Ramp", "jobs": [{"id": "other-job"}]}),
    }
    c = _client(routes)
    assert c.fetch_content(JOB_URL) is None


def test_fetch_content_none_when_board_missing():
    routes = {}  # board itself → 404
    c = _client(routes)
    assert c.fetch_content(JOB_URL) is None


def test_fetch_content_raises_on_5xx():
    routes = {BOARD_URL: (503, "unavailable")}
    c = _client(routes)
    with pytest.raises(httpx.HTTPStatusError):
        c.fetch_content(JOB_URL)


def test_fetch_content_raises_on_network_error():
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("timeout", request=req)

    http = httpx.Client(transport=httpx.MockTransport(handler))
    c = AshbyClient(http_client=http)
    with pytest.raises(httpx.HTTPError):
        c.fetch_content(JOB_URL)


def test_fetch_content_raises_on_malformed_url():
    c = _client({})
    with pytest.raises(ValueError):
        c.fetch_content("https://example.com/not-ashby")


# check_job/fetch_content рефетчат доску (board-listing) — без кэша batch-верификация
# многих вакансий с одной доски (напр. 126 живых вакансий на одном board) дала бы по
# полному GET доски НА КАЖДУЮ вакансию. Кэш держит один _board(token) на инстанс.

def _counting_client(routes: dict) -> tuple[AshbyClient, list]:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        url_str = str(request.url.copy_with(params={}))
        calls.append(url_str)
        if url_str in routes:
            status, body = routes[url_str]
            if isinstance(body, (dict, list)):
                return httpx.Response(status, json=body)
            return httpx.Response(status, text=str(body))
        return httpx.Response(404, text="not found")

    http = httpx.Client(transport=httpx.MockTransport(handler))
    return AshbyClient(http_client=http), calls


def test_board_fetched_once_across_multiple_check_job_calls():
    routes = {
        BOARD_URL: (200, {"name": "Ramp", "jobs": [
            {"id": "job-1"}, {"id": "job-2"},
        ]}),
    }
    c, calls = _counting_client(routes)
    assert c.check_job(f"{BOARD_URL}/job-1") == "live"
    assert c.check_job(f"{BOARD_URL}/job-2") == "live"
    assert c.check_job(f"{BOARD_URL}/job-3") == "gone"
    assert calls == [BOARD_URL]  # ровно один GET доски на 3 проверки


def test_board_cache_shared_between_check_job_and_fetch_content():
    routes = {
        BOARD_URL: (200, {"name": "Ramp", "jobs": [
            {"id": "job-1", "descriptionHtml": "<p>hi</p>"},
        ]}),
    }
    c, calls = _counting_client(routes)
    assert c.check_job(f"{BOARD_URL}/job-1") == "live"
    assert c.fetch_content(f"{BOARD_URL}/job-1") == "<p>hi</p>"
    assert calls == [BOARD_URL]


def test_board_cache_is_per_token():
    routes = {
        BOARD_URL: (200, {"name": "Ramp", "jobs": [{"id": "job-1"}]}),
        f"{ASHBY_BASE}/other": (200, {"name": "Other", "jobs": [{"id": "job-9"}]}),
    }
    c, calls = _counting_client(routes)
    assert c.check_job(f"{BOARD_URL}/job-1") == "live"
    assert c.check_job(f"{ASHBY_BASE}/other/job-9") == "live"
    assert set(calls) == {BOARD_URL, f"{ASHBY_BASE}/other"}
    assert len(calls) == 2


def test_board_cache_not_populated_on_5xx():
    """Транзиентная ошибка не должна залипать в кэше как 'проверено'."""
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url.copy_with(params={})))
        if len(calls) <= 3:  # исчерпать retry-попытки (DEFAULT_POLICY.max_attempts=3)
            return httpx.Response(503, text="unavailable")
        return httpx.Response(200, json={"name": "Ramp", "jobs": [{"id": "job-1"}]})

    http = httpx.Client(transport=httpx.MockTransport(handler))
    c = AshbyClient(http_client=http, sleep=lambda *a: None)
    assert c.check_job(f"{BOARD_URL}/job-1") == "error"
    assert c.check_job(f"{BOARD_URL}/job-1") == "live"
    assert len(calls) == 4  # 3 исчерпанных ретрая + 1 успешный повторный запрос
