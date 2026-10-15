from fastapi.testclient import TestClient


def _make_app(conn_factory, monkeypatch):
    import job_machine.dashboard.app as appmod
    monkeypatch.setattr(appmod.store, "count_funnel",
                        lambda conn: {"vacancy": {"discovered": 4}, "application": {}})
    monkeypatch.setattr(appmod.store, "count_blockers",
                        lambda conn: [{"blocker": "captcha", "count": 1, "oldest": None}])
    monkeypatch.setattr(appmod.mcp_store, "query_ready_queue_all",
                        lambda conn, limit: [{"application_id": "a1", "candidate_id": "andrey-s",
                                              "company": "Acme",
                                              "role": "QA", "url": "https://a/1"}])
    return appmod.create_app(conn_factory=conn_factory)


class _FakeConn:
    def close(self): pass


def test_healthz():
    import job_machine.dashboard.app as appmod
    app = appmod.create_app(conn_factory=lambda: None)
    with TestClient(app) as client:
        assert client.get("/healthz").json() == {"status": "ok"}


def test_root_returns_html_with_data(monkeypatch):
    app = _make_app(_FakeConn, monkeypatch)
    with TestClient(app) as client:
        resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "Discovered" in resp.text
    assert "captcha" in resp.text
    assert "Acme" in resp.text


def test_no_mutating_routes():
    import job_machine.dashboard.app as appmod
    app = appmod.create_app(conn_factory=lambda: None)
    methods = set()
    for r in app.routes:
        methods |= getattr(r, "methods", set()) or set()
    assert "POST" not in methods
    assert "DELETE" not in methods
    assert "PUT" not in methods
    assert "PATCH" not in methods
