import httpx
import pytest

from job_machine.fill.browser_client import BrowserClient


def _client(handler):
    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport, base_url="http://browser:8080")
    return BrowserClient(base_url="http://browser:8080", http=http)


def test_create_session_returns_id():
    def handler(req):
        assert req.method == "POST" and req.url.path == "/session"
        return httpx.Response(200, json={"session_id": "s1", "status": "open"})

    bc = _client(handler)
    assert bc.create_session() == "s1"


def test_inspect_parses_blocker():
    def handler(req):
        assert req.url.path == "/inspect"
        body = req.read().decode()
        assert "s1" in body and "https://x" in body
        return httpx.Response(200, json={"blocker": "captcha", "form_schema": None,
                                         "screenshot_path": "/a.png"})

    bc = _client(handler)
    res = bc.inspect("s1", "https://x")
    assert res.blocker == "captcha"
    assert res.form_schema is None


def test_inspect_parses_form_schema():
    schema = {"url": "https://x", "fields": [
        {"name": "job_application[email]", "field_type": "email", "required": True}]}

    def handler(req):
        return httpx.Response(200, json={"blocker": None, "form_schema": schema,
                                         "screenshot_path": None})

    bc = _client(handler)
    res = bc.inspect("s1", "https://x")
    assert res.blocker is None
    assert res.form_schema.fields[0].name == "job_application[email]"


def test_inspect_current_posts_navigate_false_no_url():
    def handler(req):
        assert req.url.path == "/inspect"
        body = req.read().decode()
        assert '"navigate":false' in body.replace(" ", "")
        assert '"url"' not in body or '"url":null' in body.replace(" ", "")
        return httpx.Response(200, json={"blocker": None, "form_schema": None,
                                         "screenshot_path": None})

    bc = _client(handler)
    res = bc.inspect_current("s1")
    assert res.blocker is None


def test_fill_posts_fields_and_resume():
    def handler(req):
        assert req.url.path == "/fill"
        return httpx.Response(200, json={"filled": ["job_application[email]"],
                                         "resume_attached": True,
                                         "stopped_before_submit": True,
                                         "unmatched": []})

    bc = _client(handler)
    res = bc.fill("s1", {"job_application[email]": "a@b.com"}, resume_path="/r.pdf")
    assert res.resume_attached is True
    assert res.stopped_before_submit is True


def test_dispose_calls_delete():
    seen = {}

    def handler(req):
        seen["method"] = req.method
        seen["path"] = req.url.path
        return httpx.Response(200, json={"status": "disposed"})

    bc = _client(handler)
    bc.dispose("s1")
    assert seen["method"] == "DELETE"
    assert seen["path"] == "/session/s1"


def test_retain_posts_to_correct_path():
    seen = {}

    def handler(req):
        seen["method"] = req.method
        seen["path"] = req.url.path
        return httpx.Response(200, json={"status": "retained", "session_id": "s1"})

    bc = _client(handler)
    bc.retain("s1")
    assert seen["method"] == "POST"
    assert seen["path"] == "/session/s1/retain"


def test_retain_raises_on_missing_session():
    def handler(req):
        return httpx.Response(404, json={"detail": "no such session"})

    bc = _client(handler)
    with pytest.raises(httpx.HTTPStatusError):
        bc.retain("nope")


def test_handoff_posts_url_returns_result():
    def handler(req):
        assert req.method == "POST"
        assert req.url.path == "/handoff"
        body = req.read().decode()
        assert "https://example.com/apply" in body
        return httpx.Response(200, json={
            "session_id": "s1",
            "status": "handoff",
            "novnc_url": "http://lab-vm:6080/vnc.html?token=s1",
        })

    bc = _client(handler)
    result = bc.handoff("https://example.com/apply")
    assert result.session_id == "s1"
    assert result.status == "handoff"
    assert result.novnc_url == "http://lab-vm:6080/vnc.html?token=s1"


def test_handoff_novnc_none():
    def handler(req):
        return httpx.Response(200, json={
            "session_id": "s2",
            "status": "handoff",
            "novnc_url": None,
        })

    bc = _client(handler)
    result = bc.handoff("https://example.com/apply")
    assert result.novnc_url is None


def test_release_posts_to_correct_path():
    seen = {}

    def handler(req):
        seen["method"] = req.method
        seen["path"] = req.url.path
        return httpx.Response(200, json={"status": "released", "session_id": "s1"})

    bc = _client(handler)
    bc.release("s1")
    assert seen["method"] == "POST"
    assert seen["path"] == "/handoff/s1/release"


def test_content_posts_session_and_url_returns_html():
    def handler(req):
        assert req.url.path == "/content"
        body = req.read().decode()
        assert "s1" in body and "hh.ru" in body
        return httpx.Response(200, json={"html": "<html>ok</html>"})

    bc = _client(handler)
    html = bc.content("s1", "https://hh.ru/search/vacancy?text=QA")
    assert html == "<html>ok</html>"
