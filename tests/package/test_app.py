from fastapi.testclient import TestClient

from job_machine.package.app import create_app


class FakeConn:
    def __init__(self): self.committed = False
    def commit(self): self.committed = True
    def close(self): pass


def test_healthz():
    app = create_app(conn_factory=lambda: FakeConn())
    client = TestClient(app)
    assert client.get("/healthz").json() == {"status": "ok"}


def test_build_route_invokes_service(monkeypatch):
    calls = {}

    def fake_build(conn, base_dir, limit, candidate_id=None):
        calls["base_dir"] = base_dir
        calls["limit"] = limit
        return 3

    import job_machine.package.app as appmod
    monkeypatch.setattr(appmod.service, "run_package_build", fake_build)
    app = create_app(conn_factory=lambda: FakeConn())
    client = TestClient(app)
    resp = client.post("/package/build", json={"limit": 5})
    assert resp.status_code == 200
    assert resp.json() == {"built": 3}
    assert calls["limit"] == 5


def test_build_route_passes_candidate_id(monkeypatch):
    """/package/build прокидывает candidate_id из тела в сервис; отсутствие ключа → None
    (глобальный auto-свип, обратная совместимость с n8n-триггером). Скоуп нужен, т.к.
    упаковка идёт через воркер (у него /data), а не локально."""
    calls = {}

    def fake_build(conn, base_dir, limit, candidate_id=None):
        calls["candidate_id"] = candidate_id
        return 0

    import job_machine.package.app as appmod
    monkeypatch.setattr(appmod.service, "run_package_build", fake_build)
    app = create_app(conn_factory=lambda: FakeConn())
    client = TestClient(app)
    resp = client.post("/package/build", json={"limit": 5, "candidate_id": "daria-b"})
    assert resp.status_code == 200
    assert calls["candidate_id"] == "daria-b"

    client.post("/package/build", json={"limit": 5})
    assert calls["candidate_id"] is None


def test_no_submit_or_browser_routes():
    app = create_app(conn_factory=lambda: FakeConn())
    paths = {r.path for r in app.routes}
    assert "/healthz" in paths and "/package/build" in paths
    assert not any("submit" in p or "fill" in p for p in paths)
