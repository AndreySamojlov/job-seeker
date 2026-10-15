from fastapi.testclient import TestClient


def _make_app(conn_factory):
    from job_machine.approval.app import create_app
    return create_app(conn_factory=conn_factory)


def test_healthz():
    app = _make_app(conn_factory=lambda: None)
    with TestClient(app) as client:
        assert client.get("/healthz").json() == {"status": "ok"}


def test_routes_exist():
    app = _make_app(conn_factory=lambda: None)
    paths = {r.path for r in app.routes}
    assert "/approval/request" in paths
    assert "/approval/approve" in paths
    assert "/approval/reject" in paths
    assert "/approval/status/{application_id}" in paths
    assert "/submit" not in paths


def test_approval_request_returns_count(monkeypatch):
    import job_machine.approval.app as appmod

    class _FakeConn:
        def close(self): pass

    monkeypatch.setattr(appmod.service, "process_approval_request",
                        lambda conn, limit: {"count": 2, "items": []})
    a = appmod.create_app(conn_factory=_FakeConn)
    with TestClient(a) as client:
        resp = client.post("/approval/request", json={"limit": 5})
    assert resp.json()["count"] == 2


def test_approve_delegates_to_store(monkeypatch):
    import job_machine.approval.app as appmod

    class _FakeConn:
        def close(self): pass
        def commit(self): pass

    called = {}
    monkeypatch.setattr(appmod.store, "approve",
                        lambda conn, aid: (called.update({"aid": aid}) or True))
    a = appmod.create_app(conn_factory=_FakeConn)
    with TestClient(a) as client:
        resp = client.post("/approval/approve", json={"application_id": "abc-123"})
    assert resp.json()["approved"] is True
    assert called["aid"] == "abc-123"
