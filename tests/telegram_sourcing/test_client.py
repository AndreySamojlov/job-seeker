import httpx
import pytest

from job_machine.telegram_sourcing.client import TelegramPreviewClient


def _client(handler):
    return TelegramPreviewClient(http_client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_fetch_channel_html_returns_body_on_200():
    def handler(request):
        assert request.url.path == "/s/forallqa"
        return httpx.Response(200, text="<html>posts</html>")
    assert _client(handler).fetch_channel_html("forallqa") == "<html>posts</html>"


def test_fetch_channel_html_none_on_404():
    def handler(request):
        return httpx.Response(404, text="not found")
    assert _client(handler).fetch_channel_html("nosuchchannel") is None


def test_fetch_channel_html_raises_on_5xx():
    def handler(request):
        return httpx.Response(503, text="")
    with pytest.raises(httpx.HTTPStatusError):
        _client(handler).fetch_channel_html("forallqa")


def test_fetch_channel_html_none_on_redirect():
    def handler(request):
        return httpx.Response(302, headers={"location": "https://t.me/relocaty_jobs"})
    assert _client(handler).fetch_channel_html("relocaty_jobs") is None


def test_fetch_channel_html_retries_on_503_then_succeeds():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503)
        return httpx.Response(200, text="<html>ok</html>")

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = TelegramPreviewClient(http_client=http_client, sleep=lambda _s: None)
    assert client.fetch_channel_html("forallqa") == "<html>ok</html>"
    assert calls["n"] == 2
