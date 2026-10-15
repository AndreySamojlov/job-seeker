import httpx
import pytest

from job_machine.discovery.greenhouse import GreenhouseClient


def _client(handler):
    return GreenhouseClient(http_client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_list_jobs_retries_on_503_then_succeeds():
    """list_jobs должен пережить транзиентный 503 через retry-слой."""
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"jobs": []})

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = GreenhouseClient(http_client=http_client, sleep=lambda _s: None)
    jobs = client.list_jobs("acme")
    assert jobs == []
    assert calls["n"] == 2


def test_list_jobs_parses_board_payload():
    def handler(request):
        assert request.url.path == "/v1/boards/acme/jobs"
        return httpx.Response(200, json={"jobs": [
            {"id": 1, "title": "A", "absolute_url": "https://boards.greenhouse.io/acme/jobs/1",
             "location": {"name": "Remote"}},
            {"id": 2, "title": "B", "absolute_url": "https://boards.greenhouse.io/acme/jobs/2"},
        ]})
    jobs = _client(handler).list_jobs("acme")
    assert [j.id for j in jobs] == [1, 2]
    assert jobs[0].location_name == "Remote"


def test_get_board_name():
    def handler(request):
        return httpx.Response(200, json={"name": "Acme Corp"})
    assert _client(handler).get_board_name("acme") == "Acme Corp"


def test_get_board_name_none_on_404():
    def handler(request):
        return httpx.Response(404, json={"status": 404})
    assert _client(handler).get_board_name("missing") is None


def test_check_job_live_gone_error():
    def make(status):
        def handler(request):
            return httpx.Response(status, json={})
        return _client(handler)
    url = "https://boards-api.greenhouse.io/v1/boards/acme/jobs/1"
    assert make(200).check_job(url) == "live"
    assert make(404).check_job(url) == "gone"
    assert make(500).check_job(url) == "error"


def test_check_job_network_error_is_error():
    def handler(request):
        raise httpx.ConnectError("boom")
    url = "https://boards-api.greenhouse.io/v1/boards/acme/jobs/1"
    assert _client(handler).check_job(url) == "error"


def test_fetch_content_returns_content_field():
    def handler(request):
        return httpx.Response(200, json={"content": "&lt;p&gt;hello&lt;/p&gt;"})
    url = "https://boards-api.greenhouse.io/v1/boards/acme/jobs/1"
    assert _client(handler).fetch_content(url) == "&lt;p&gt;hello&lt;/p&gt;"


def test_fetch_content_none_on_404():
    def handler(request):
        return httpx.Response(404, json={})
    url = "https://boards-api.greenhouse.io/v1/boards/acme/jobs/1"
    assert _client(handler).fetch_content(url) is None


def test_fetch_content_raises_on_network_error():
    # Транзиентная сетевая ошибка должна пробрасываться, а не тихо превращаться в
    # None — иначе вызывающий код (triage) не отличит её от подтверждённого 404
    # и навсегда пометит живую вакансию 'stale'.
    def handler(request):
        raise httpx.ConnectError("boom")
    url = "https://boards-api.greenhouse.io/v1/boards/acme/jobs/1"
    with pytest.raises(httpx.HTTPError):
        _client(handler).fetch_content(url)


def test_fetch_content_raises_on_5xx():
    def handler(request):
        return httpx.Response(503, json={})
    url = "https://boards-api.greenhouse.io/v1/boards/acme/jobs/1"
    with pytest.raises(httpx.HTTPStatusError):
        _client(handler).fetch_content(url)
