"""Тесты build_novnc_url."""
from urllib.parse import urlparse, parse_qs

from job_machine.browser.novnc import build_novnc_url


def test_basic_url_structure():
    url = build_novnc_url("http://lab-vm:6080", "abc")
    assert url is not None
    parsed = urlparse(url)
    assert parsed.scheme == "http"
    assert parsed.netloc == "lab-vm:6080"
    assert "vnc.html" in parsed.path
    qs = parse_qs(parsed.query)
    assert qs["token"] == ["abc"]
    assert qs["autoconnect"] == ["1"]


def test_trailing_slash_stripped():
    url = build_novnc_url("http://lab-vm:6080/", "abc")
    assert url is not None
    # не должно быть двойного слэша
    assert "//vnc" not in url


def test_empty_base_url_returns_none():
    assert build_novnc_url("", "abc") is None


def test_none_base_url_returns_none():
    assert build_novnc_url(None, "abc") is None


def test_websockify_and_resize_params():
    url = build_novnc_url("http://lab-vm:6080", "sid123")
    qs = parse_qs(urlparse(url).query)
    # path=websockify для проксирования VNC через WebSocket
    assert "path" in qs
    assert qs["path"] == ["websockify"]
    # resize=remote — масштабирование дисплея
    assert qs.get("resize") == ["remote"]
