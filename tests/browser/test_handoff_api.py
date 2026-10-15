"""Тесты эндпоинтов /handoff и /handoff/{sid}/release."""
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
pytest.importorskip("playwright")

from fastapi.testclient import TestClient

from job_machine.browser.app import create_app


class FakeHandoffManager:
    """Менеджер без браузера — поддерживает persist-aware API."""

    def __init__(self):
        self._sessions = {}   # sid → {persist, goto_called_with}

    async def create_session(self, persist: bool = False):
        sid = "s1"
        self._sessions[sid] = {"persist": persist, "goto_called_with": None}
        return sid

    def info(self, sid):
        sess = self._sessions.get(sid)
        if sess is None:
            return None
        status = "handoff" if sess["persist"] else "open"
        return {"session_id": sid, "status": status, "current_url": None}

    def get_page(self, sid):
        """Возвращает FakePage для вызова goto."""
        if sid not in self._sessions:
            raise KeyError(sid)

        sessions = self._sessions
        class FakePage:
            async def goto(self_, url, **kw):
                sessions[sid]["goto_called_with"] = url

        return FakePage()

    async def dispose_session(self, sid, force: bool = False):
        sess = self._sessions.get(sid)
        if sess is None:
            return
        if sess["persist"] and not force:
            return  # persist-сессия выживает
        del self._sessions[sid]

    def artifact_path(self, sid, suffix):
        return f"/tmp/{sid}_{suffix}"

    def goto_was_called_with(self, sid):
        """Возвращает URL который был передан в goto (для assert)."""
        return self._sessions.get(sid, {}).get("goto_called_with")


def test_handoff_creates_persist_session():
    mgr = FakeHandoffManager()
    app = create_app(manager=mgr)
    with TestClient(app) as client:
        resp = client.post("/handoff", json={"url": "https://example.com/apply"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["session_id"] == "s1"
    assert data["status"] == "handoff"


def test_handoff_calls_goto(monkeypatch):
    mgr = FakeHandoffManager()
    monkeypatch.delenv("NOVNC_BASE_URL", raising=False)
    app = create_app(manager=mgr)
    with TestClient(app) as client:
        client.post("/handoff", json={"url": "https://example.com/apply"})
    assert mgr.goto_was_called_with("s1") == "https://example.com/apply"


def test_handoff_novnc_url_when_env_set(monkeypatch):
    monkeypatch.setenv("NOVNC_BASE_URL", "http://lab-vm:6080")
    mgr = FakeHandoffManager()
    app = create_app(manager=mgr)
    with TestClient(app) as client:
        resp = client.post("/handoff", json={"url": "https://example.com/apply"})
    data = resp.json()
    assert data["novnc_url"] is not None
    assert "token=s1" in data["novnc_url"]


def test_handoff_novnc_url_none_without_env(monkeypatch):
    monkeypatch.delenv("NOVNC_BASE_URL", raising=False)
    mgr = FakeHandoffManager()
    app = create_app(manager=mgr)
    with TestClient(app) as client:
        resp = client.post("/handoff", json={"url": "https://example.com/apply"})
    assert resp.json()["novnc_url"] is None


def test_handoff_session_survives_regular_delete(monkeypatch):
    """DELETE /session/s1 НЕ убивает persist-сессию."""
    monkeypatch.delenv("NOVNC_BASE_URL", raising=False)
    mgr = FakeHandoffManager()
    app = create_app(manager=mgr)
    with TestClient(app) as client:
        client.post("/handoff", json={"url": "https://example.com/apply"})
        # обычный DELETE не должен убить persist
        client.delete("/session/s1")
        # сессия всё ещё есть
        assert client.get("/session/s1").status_code == 200


def test_release_kills_persist_session(monkeypatch):
    monkeypatch.delenv("NOVNC_BASE_URL", raising=False)
    mgr = FakeHandoffManager()
    app = create_app(manager=mgr)
    with TestClient(app) as client:
        client.post("/handoff", json={"url": "https://example.com/apply"})
        resp = client.post("/handoff/s1/release")
        assert resp.status_code == 200
        # после release сессии нет
        assert client.get("/session/s1").status_code == 404
