import httpx
import pytest

from job_machine.discovery.manual import ManualClient


def _client(handler):
    return ManualClient(http_client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_fetch_content_returns_raw_html_body():
    def handler(request):
        return httpx.Response(200, text="<html><body><h1>QA Engineer</h1></body></html>")
    url = "https://example.com/careers/qa-engineer"
    assert _client(handler).fetch_content(url) == (
        "<html><body><h1>QA Engineer</h1></body></html>"
    )


def test_fetch_content_none_on_404():
    def handler(request):
        return httpx.Response(404, text="not found")
    assert _client(handler).fetch_content("https://example.com/gone") is None


def test_fetch_content_raises_on_network_error():
    # Как GreenhouseClient: транзиентная ошибка должна пробрасываться, а не
    # тихо превращаться в None — иначе вызывающий код (triage) навсегда
    # похоронит вакансию как stale вместо ретрая на следующем pull.
    def handler(request):
        raise httpx.ConnectError("boom")
    with pytest.raises(httpx.HTTPError):
        _client(handler).fetch_content("https://example.com/careers/qa-engineer")


def test_fetch_content_raises_on_5xx():
    def handler(request):
        return httpx.Response(503, text="")
    with pytest.raises(httpx.HTTPStatusError):
        _client(handler).fetch_content("https://example.com/careers/qa-engineer")


def test_fetch_content_retries_on_503_then_succeeds():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503)
        return httpx.Response(200, text="<p>role</p>")

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = ManualClient(http_client=http_client, sleep=lambda _s: None)
    assert client.fetch_content("https://example.com/careers/qa-engineer") == "<p>role</p>"
    assert calls["n"] == 2
