from fastapi.testclient import TestClient


def test_healthz_and_routes_exist():
    from job_machine.submit.app import create_app
    app = create_app(conn_factory=lambda: None, browser_factory=lambda: None)
    with TestClient(app) as client:
        assert client.get("/healthz").json() == {"status": "ok"}
    paths = {r.path for r in app.routes}
    assert "/submit/run" in paths
    assert "/submit" not in paths   # browser primitive not exposed here


def test_submit_run_returns_summary(monkeypatch):
    import job_machine.submit.app as appmod

    class _Conn:
        def close(self): pass

    monkeypatch.setattr(appmod.runtime_control, "is_submit_enabled",
                        lambda conn: True)
    monkeypatch.setattr(appmod.service, "run_submit",
                        lambda conn, browser, limit: appmod.SubmitRunSummary(
                            pulled=1, submitted=1))
    app = appmod.create_app(conn_factory=_Conn, browser_factory=lambda: object())
    with TestClient(app) as client:
        resp = client.post("/submit/run", json={"limit": 5})
    assert resp.json()["submitted"] == 1


def test_submit_one_route_exists_and_delegates():
    from job_machine.submit.app import create_app
    app = create_app(conn_factory=lambda: None, browser_factory=lambda: None)
    paths = {r.path for r in app.routes}
    assert "/submit/one" in paths
    assert "/application/{application_id}/detail" in paths


def test_submit_one_submits_single_application(monkeypatch):
    import job_machine.submit.app as appmod

    class _Conn:
        def close(self): pass

    seen = {}

    def _fake_run_one(conn, browser, application_id):
        seen["aid"] = application_id
        return appmod.SubmitRunSummary(pulled=1, submitted=1)

    monkeypatch.setattr(appmod.runtime_control, "is_submit_enabled",
                        lambda conn: True)
    monkeypatch.setattr(appmod.service, "run_submit_one", _fake_run_one)
    app = appmod.create_app(conn_factory=_Conn, browser_factory=lambda: object())
    with TestClient(app) as client:
        resp = client.post("/submit/one", json={"application_id": "a1"})
    assert resp.json()["submitted"] == 1
    assert seen["aid"] == "a1"


def test_detail_endpoint_returns_summary(monkeypatch):
    """Воркер читает disclosed-summary с /data (у MCP его нет локально)."""
    import job_machine.submit.app as appmod

    class _Conn:
        def close(self): pass

    monkeypatch.setattr(appmod.mcp_store, "load_application_detail",
                        lambda conn, aid: {"application_id": aid, "company": "Acme",
                                           "summary_md": "# Сводка"})
    app = appmod.create_app(conn_factory=_Conn, browser_factory=lambda: object())
    with TestClient(app) as client:
        resp = client.get("/application/a1/detail")
    assert resp.json()["company"] == "Acme"
    assert resp.json()["summary_md"] == "# Сводка"
