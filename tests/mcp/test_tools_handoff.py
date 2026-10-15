"""Тесты handoff_browser tool: инвариант безопасности + логика."""
import pytest
from unittest.mock import patch, MagicMock

import httpx

from job_machine.mcp import tools


# ─── FakeBrowser ────────────────────────────────────────────────────────────

class FakeBrowser:
    """Mock браузер-клиента с инвариантом: submit невызываем."""

    def __init__(self, handoff_result=None, released_raises=False):
        self._handoff_result = handoff_result or _make_handoff_result()
        self._handoff_calls = []
        self.released = []
        self._released_raises = released_raises

    def handoff(self, url: str):
        self._handoff_calls.append(url)
        return self._handoff_result

    def release(self, session_id: str) -> None:
        self.released.append(session_id)
        if self._released_raises:
            req = httpx.Request("POST", f"http://x/handoff/{session_id}/release")
            resp = httpx.Response(404, request=req)
            raise httpx.HTTPStatusError("404", request=req, response=resp)

    def submit(self, *a, **kw):
        raise AssertionError(
            "handoff_browser НИКОГДА не должен вызывать submit — инвариант §3/§4 ТЗ"
        )


def _make_handoff_result(session_id="s1", novnc_url=None):
    from job_machine.browser.schema import HandoffResult
    return HandoffResult(session_id=session_id, status="handoff", novnc_url=novnc_url)


# ─── FakeConn ────────────────────────────────────────────────────────────────

class FakeConn:
    def __init__(self):
        self.committed = False

    def commit(self):
        self.committed = True


# ─── тесты ───────────────────────────────────────────────────────────────────

def test_handoff_browser_calls_handoff_not_submit(monkeypatch):
    """Инвариант: FakeBrowser.submit → AssertionError, handoff_browser его не зовёт."""
    browser = FakeBrowser()

    monkeypatch.setattr(
        tools.handoff_store, "load_destination_url",
        lambda conn, aid: "https://example.com/apply",
    )
    monkeypatch.setattr(
        tools.handoff_store, "load_active_handoff_session_id",
        lambda conn, aid: None,
    )
    monkeypatch.setattr(
        tools.handoff_store, "record_handoff_manual",
        lambda *a, **kw: None,
    )

    conn = FakeConn()
    result = tools.handoff_browser(conn, browser, "app1")
    assert result["ok"] is True
    assert browser._handoff_calls == ["https://example.com/apply"]


def test_handoff_browser_returns_session_and_novnc(monkeypatch):
    """Возвращает session_id, novnc_url, status, instructions."""
    br = FakeBrowser(handoff_result=_make_handoff_result(
        session_id="s99", novnc_url="http://lab:6080/vnc.html?token=s99"
    ))

    monkeypatch.setattr(
        tools.handoff_store, "load_destination_url",
        lambda conn, aid: "https://example.com/apply",
    )
    monkeypatch.setattr(
        tools.handoff_store, "load_active_handoff_session_id",
        lambda conn, aid: None,
    )
    monkeypatch.setattr(
        tools.handoff_store, "record_handoff_manual",
        lambda *a, **kw: None,
    )

    conn = FakeConn()
    result = tools.handoff_browser(conn, br, "app1")
    assert result["ok"] is True
    assert result["session_id"] == "s99"
    assert result["novnc_url"] == "http://lab:6080/vnc.html?token=s99"
    assert result["status"] == "handoff"
    assert "instructions" in result


def test_handoff_browser_no_url_returns_ok_false(monkeypatch):
    """Если URL не найден — {ok: False}, сессия не создаётся, state не меняется."""
    br = FakeBrowser()

    monkeypatch.setattr(
        tools.handoff_store, "load_destination_url",
        lambda conn, aid: None,
    )
    record_calls = []
    monkeypatch.setattr(
        tools.handoff_store, "record_handoff_manual",
        lambda *a, **kw: record_calls.append(a),
    )

    conn = FakeConn()
    result = tools.handoff_browser(conn, br, "app1")
    assert result["ok"] is False
    assert br._handoff_calls == []     # handoff() НЕ вызывался
    assert record_calls == []          # record() НЕ вызывался
    assert conn.committed is False     # commit() НЕ вызывался


def test_handoff_browser_novnc_none_gives_instructions_with_port(monkeypatch):
    """Если novnc_url=None — инструкции упоминают порт 6080 туннеля."""
    br = FakeBrowser(handoff_result=_make_handoff_result(novnc_url=None))

    monkeypatch.setattr(
        tools.handoff_store, "load_destination_url",
        lambda conn, aid: "https://example.com/apply",
    )
    monkeypatch.setattr(
        tools.handoff_store, "load_active_handoff_session_id",
        lambda conn, aid: None,
    )
    monkeypatch.setattr(
        tools.handoff_store, "record_handoff_manual",
        lambda *a, **kw: None,
    )

    conn = FakeConn()
    result = tools.handoff_browser(conn, br, "app1")
    assert result["ok"] is True
    assert result["novnc_url"] is None
    assert "6080" in result["instructions"]


def test_handoff_browser_commits_conn(monkeypatch):
    """После успешного handoff — conn.commit() вызывается."""
    br = FakeBrowser()

    monkeypatch.setattr(
        tools.handoff_store, "load_destination_url",
        lambda conn, aid: "https://example.com/apply",
    )
    monkeypatch.setattr(
        tools.handoff_store, "load_active_handoff_session_id",
        lambda conn, aid: None,
    )
    monkeypatch.setattr(
        tools.handoff_store, "record_handoff_manual",
        lambda *a, **kw: None,
    )

    conn = FakeConn()
    tools.handoff_browser(conn, br, "app1")
    assert conn.committed is True


def test_fake_browser_submit_raises():
    """Кодифицирует инвариант: FakeBrowser.submit → AssertionError."""
    br = FakeBrowser()
    with pytest.raises(AssertionError, match="инвариант"):
        br.submit()


def test_handoff_browser_releases_previous_session(monkeypatch):
    """Повторный handoff для ТОЙ ЖЕ заявки освобождает старую persist-сессию —
    иначе она утекает (никогда не disposed)."""
    br = FakeBrowser()
    monkeypatch.setattr(
        tools.handoff_store, "load_destination_url",
        lambda conn, aid: "https://example.com/apply",
    )
    monkeypatch.setattr(
        tools.handoff_store, "load_active_handoff_session_id",
        lambda conn, aid: "old-sid",
    )
    monkeypatch.setattr(tools.handoff_store, "record_handoff_manual", lambda *a, **kw: None)

    conn = FakeConn()
    tools.handoff_browser(conn, br, "app1")
    assert br.released == ["old-sid"]


def test_handoff_browser_no_previous_session_skips_release(monkeypatch):
    br = FakeBrowser()
    monkeypatch.setattr(
        tools.handoff_store, "load_destination_url",
        lambda conn, aid: "https://example.com/apply",
    )
    monkeypatch.setattr(
        tools.handoff_store, "load_active_handoff_session_id",
        lambda conn, aid: None,
    )
    monkeypatch.setattr(tools.handoff_store, "record_handoff_manual", lambda *a, **kw: None)

    conn = FakeConn()
    tools.handoff_browser(conn, br, "app1")
    assert br.released == []


def test_handoff_browser_release_404_does_not_block_new_handoff(monkeypatch):
    """Старая сессия уже протухла (воркер перезапущен) — release кидает 404,
    новый handoff всё равно проходит."""
    br = FakeBrowser(released_raises=True)
    monkeypatch.setattr(
        tools.handoff_store, "load_destination_url",
        lambda conn, aid: "https://example.com/apply",
    )
    monkeypatch.setattr(
        tools.handoff_store, "load_active_handoff_session_id",
        lambda conn, aid: "dead-sid",
    )
    monkeypatch.setattr(tools.handoff_store, "record_handoff_manual", lambda *a, **kw: None)

    conn = FakeConn()
    result = tools.handoff_browser(conn, br, "app1")
    assert result["ok"] is True
    assert br._handoff_calls == ["https://example.com/apply"]


def test_handoff_browser_release_non_404_error_propagates(monkeypatch):
    """Не-404 ошибка release (например 500 воркера) НЕ должна проглатываться —
    это реальная эксплуатационная проблема, а не 'сессия уже не существует'."""
    class Explode500Browser(FakeBrowser):
        def release(self, session_id):
            req = httpx.Request("POST", f"http://x/handoff/{session_id}/release")
            resp = httpx.Response(500, request=req)
            raise httpx.HTTPStatusError("500", request=req, response=resp)

    br = Explode500Browser()
    monkeypatch.setattr(
        tools.handoff_store, "load_destination_url",
        lambda conn, aid: "https://example.com/apply",
    )
    monkeypatch.setattr(
        tools.handoff_store, "load_active_handoff_session_id",
        lambda conn, aid: "some-sid",
    )
    monkeypatch.setattr(tools.handoff_store, "record_handoff_manual", lambda *a, **kw: None)

    conn = FakeConn()
    with pytest.raises(httpx.HTTPStatusError):
        tools.handoff_browser(conn, br, "app1")


# ─── resume_fill ─────────────────────────────────────────────────────────

class FakeFillWorker:
    def __init__(self, result=None):
        self._result = result or {"ok": True, "status": "pre_submit_ready"}
        self.calls = []

    def resume_after_handoff(self, application_id, session_id):
        self.calls.append((application_id, session_id))
        return self._result


def test_resume_fill_no_active_session_returns_ok_false(monkeypatch):
    monkeypatch.setattr(tools.handoff_store, "load_active_handoff_session_id",
                        lambda conn, aid: None)
    worker = FakeFillWorker()
    result = tools.resume_fill(FakeConn(), worker, "app1")
    assert result == {"ok": False, "error": "no_active_session"}
    assert worker.calls == []


def test_resume_fill_delegates_to_fill_worker(monkeypatch):
    monkeypatch.setattr(tools.handoff_store, "load_active_handoff_session_id",
                        lambda conn, aid: "s99")
    worker = FakeFillWorker(result={"ok": True, "status": "pre_submit_ready"})
    result = tools.resume_fill(FakeConn(), worker, "app1")
    assert result == {"ok": True, "status": "pre_submit_ready"}
    assert worker.calls == [("app1", "s99")]
