from fastapi.testclient import TestClient

from job_machine.fill.app import create_app
from job_machine.fill.models import FillRunSummary


class _Conn:
    def close(self):
        pass


def test_healthz():
    app = create_app(conn_factory=lambda: _Conn(),
                     browser_factory=lambda: object())
    client = TestClient(app)
    assert client.get("/healthz").json() == {"status": "ok"}


def test_fill_run_invokes_service(monkeypatch):
    captured = {}

    def fake_run(conn, browser, limit, candidate_id=None):
        captured["limit"] = limit
        return FillRunSummary(pulled=3, pre_submit_ready=1, blocked=2)

    monkeypatch.setattr("job_machine.fill.app.service.run_fill", fake_run)
    app = create_app(conn_factory=lambda: _Conn(), browser_factory=lambda: object())
    client = TestClient(app)
    resp = client.post("/fill/run", json={"limit": 5})
    assert resp.status_code == 200
    body = resp.json()
    assert captured["limit"] == 5
    assert body["pre_submit_ready"] == 1 and body["blocked"] == 2


def test_fill_run_passes_candidate_id(monkeypatch):
    """/fill/run прокидывает candidate_id из тела запроса в сервис; отсутствие ключа →
    None (глобальный свип, обратная совместимость с n8n-триггером)."""
    captured = {}

    def fake_run(conn, browser, limit, candidate_id=None):
        captured["candidate_id"] = candidate_id
        return FillRunSummary()

    monkeypatch.setattr("job_machine.fill.app.service.run_fill", fake_run)
    app = create_app(conn_factory=lambda: _Conn(), browser_factory=lambda: object())
    client = TestClient(app)
    resp = client.post("/fill/run", json={"limit": 5, "candidate_id": "daria-b"})
    assert resp.status_code == 200
    assert captured["candidate_id"] == "daria-b"

    client.post("/fill/run", json={"limit": 5})
    assert captured["candidate_id"] is None


def test_no_submit_route():
    app = create_app(conn_factory=lambda: _Conn(), browser_factory=lambda: object())
    paths = {r.path for r in app.routes}
    assert "/submit" not in paths
    assert "/fill/submit" not in paths


def test_fill_resume_invokes_service(monkeypatch):
    captured = {}

    def fake_resume(conn, browser, application_id, session_id):
        captured["application_id"] = application_id
        captured["session_id"] = session_id
        return {"ok": True, "status": "pre_submit_ready"}

    monkeypatch.setattr("job_machine.fill.app.service.resume_after_handoff", fake_resume)
    app = create_app(conn_factory=lambda: _Conn(), browser_factory=lambda: object())
    client = TestClient(app)
    resp = client.post("/fill/resume", json={"application_id": "app1", "session_id": "s1"})
    assert resp.status_code == 200
    assert captured == {"application_id": "app1", "session_id": "s1"}
    assert resp.json() == {"ok": True, "status": "pre_submit_ready"}


def test_no_resume_route_conflicts_with_submit():
    """/fill/resume не имеет ничего общего с submit — маршрут /submit по-прежнему
    отсутствует (устав §3)."""
    app = create_app(conn_factory=lambda: _Conn(), browser_factory=lambda: object())
    paths = {r.path for r in app.routes}
    assert "/fill/resume" in paths
    assert "/submit" not in paths


def test_fill_resume_missing_field_returns_422():
    """Тело без session_id — чистая 422 на границе API, а не KeyError→500."""
    app = create_app(conn_factory=lambda: _Conn(), browser_factory=lambda: object())
    client = TestClient(app)
    resp = client.post("/fill/resume", json={"application_id": "app1"})
    assert resp.status_code == 422
