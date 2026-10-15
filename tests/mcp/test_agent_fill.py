"""Agent tool contracts; absence of a client submit method is not CDP isolation."""
import pytest

from job_machine.mcp import tools
from types import SimpleNamespace

WORKER = SimpleNamespace(agent_context=lambda *a: {"ok":True,"answers":[{"field":"phone","value":"+1 555"}]})


# ─── FakeBrowser ────────────────────────────────────────────────────────────

class FakeBrowser:
    """Мок browser-клиента агент-пути: submit физически невызываем (нет метода)."""

    def __init__(self, released_raises=False):
        self.released = []
        self._released_raises = released_raises

    def readiness(self, session_id):
        return {"ready": True, "url": "https://example.com/apply", "blocker": None}

    def release(self, session_id: str) -> None:
        self.released.append(session_id)


def test_fake_browser_has_no_submit():
    """Кодифицирует инвариант §3/§4: FakeBrowser вообще не умеет submit —
    как и настоящий BrowserClient, используемый в server.py для агент-пути."""
    br = FakeBrowser()
    assert not hasattr(br, "submit")


# ─── FakeConn ────────────────────────────────────────────────────────────────

class FakeConn:
    def __init__(self):
        self.committed = False

    def commit(self):
        self.committed = True


_LIVE = {
    "session_id": "s1",
    "started_at": None,
    "page_url": "https://example.com/apply",
    "unmatched": ["question_123", "question_456"],
}


# ─── agent_fill_start ────────────────────────────────────────────────────────

def test_agent_fill_start_returns_session_page_unmatched_answers(monkeypatch):
    monkeypatch.setattr(tools.agent_fill_store, "load_agent_fill",
                        lambda conn, aid: dict(_LIVE))

    result = tools.agent_fill_start(FakeConn(), "app1", WORKER)

    assert result["ok"] is True
    assert result["session_id"] == "s1"
    assert result["page_url"] == "https://example.com/apply"
    assert result["unmatched"] == ["question_123", "question_456"]
    assert result["answers"] == [{"field": "phone", "value": "+1 555"}]
    assert "instructions" in result


def test_agent_fill_start_wrong_state_returns_ok_false(monkeypatch):
    monkeypatch.setattr(tools.agent_fill_store, "load_agent_fill",
                        lambda conn, aid: None)

    result = tools.agent_fill_start(FakeConn(), "app1", WORKER)

    assert result == {"ok": False, "error": "not_agent_fill_pending",
                      "application_id": "app1"}


# ─── agent_fill_done ─────────────────────────────────────────────────────────

def test_agent_fill_done_still_unmatched_rejects(monkeypatch):
    """Непустой inspect_unmatched → отказ; сессия НЕ освобождается, state не меняется."""
    monkeypatch.setattr(tools.agent_fill_store, "load_agent_fill",
                        lambda conn, aid: dict(_LIVE))
    record_calls = []
    monkeypatch.setattr(tools.agent_fill_store, "record_agent_fill_done",
                        lambda *a, **kw: (record_calls.append(a) or True))

    br = FakeBrowser()
    conn = FakeConn()
    result = tools.agent_fill_done(conn, br, "app1", ["question_456"], session_id="s1")

    assert result == {"ok": False, "error": "still_unmatched",
                      "unmatched": ["question_456"]}
    assert record_calls == []
    assert br.released == []
    assert conn.committed is False


def test_agent_fill_done_empty_unmatched_succeeds(monkeypatch):
    """Пустой остаток → pre_submit_ready, session_id сохраняется в БД, страница
    остаётся живой до отдельного submit."""
    monkeypatch.setattr(tools.agent_fill_store, "load_agent_fill",
                        lambda conn, aid: dict(_LIVE))
    record_calls = []
    monkeypatch.setattr(tools.agent_fill_store, "record_agent_fill_done",
                        lambda *a, **kw: (record_calls.append(a) or True))

    br = FakeBrowser()
    conn = FakeConn()
    result = tools.agent_fill_done(conn, br, "app1", [], session_id="s1")

    assert result["ok"] is True
    assert result["status"] == "pre_submit_ready"
    assert record_calls == [(conn, "app1", "s1")]
    assert conn.committed is True
    # Сессия НЕ освобождается: страницу ждёт submit-воркер, он кликает на ней же.
    assert br.released == []
    assert result["session_id"] == "s1"


def test_agent_fill_done_wrong_state_returns_ok_false(monkeypatch):
    monkeypatch.setattr(tools.agent_fill_store, "load_agent_fill",
                        lambda conn, aid: None)
    br = FakeBrowser()
    result = tools.agent_fill_done(FakeConn(), br, "app1", [], session_id="s1")
    assert result == {"ok": False, "error": "not_agent_fill_pending",
                      "application_id": "app1"}
    assert br.released == []


# ─── agent_fill_blocked ──────────────────────────────────────────────────────

def test_agent_fill_blocked_sets_reason_and_releases(monkeypatch):
    monkeypatch.setattr(tools.agent_fill_store, "load_agent_fill",
                        lambda conn, aid: dict(_LIVE))
    record_calls = []
    monkeypatch.setattr(tools.agent_fill_store, "record_agent_fill_blocked",
                        lambda *a, **kw: (record_calls.append(a) or True))

    br = FakeBrowser()
    conn = FakeConn()
    result = tools.agent_fill_blocked(conn, br, "app1", "missing_fact", session_id="s1")

    assert result["ok"] is True
    assert result["status"] == "fill_blocked"
    assert result["reason"] == "missing_fact"
    assert record_calls == [(conn, "app1", "missing_fact", "s1")]
    assert conn.committed is True
    assert br.released == ["s1"]


def test_agent_fill_blocked_wrong_state_returns_ok_false(monkeypatch):
    monkeypatch.setattr(tools.agent_fill_store, "load_agent_fill",
                        lambda conn, aid: None)
    br = FakeBrowser()
    result = tools.agent_fill_blocked(FakeConn(), br, "app1", "captcha", session_id="s1")
    assert result == {"ok": False, "error": "not_agent_fill_pending",
                      "application_id": "app1"}
    assert br.released == []


# ─── регистрация в server.py (submit-способный клиент недостижим по конструкции) ──

def test_agent_fill_tools_registered_with_browserclient():
    """agent_fill_* используют BrowserClient (нет .submit), НЕ SubmitBrowserClient —
    submit физически недостижим через эти инструменты (§3/§4)."""
    import inspect
    from job_machine.mcp import server
    src = inspect.getsource(server)
    for name in ("agent_fill_start", "agent_fill_done", "agent_fill_blocked"):
        assert f"def {name}(" in src
    # Секция agent_fill_* использует BrowserClient, а не SubmitBrowserClient —
    # грубая, но говорящая проверка по исходнику (юнит-тест не поднимает FastMCP).
    idx = src.index("def agent_fill_start(")
    section = src[idx:idx + 2000]
    assert "= BrowserClient(base_url=_BROWSER_URL)" in section
    assert "SubmitBrowserClient(base_url=" not in section
