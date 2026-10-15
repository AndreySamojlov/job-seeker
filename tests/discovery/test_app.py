from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from job_machine.discovery import app as appmod
from job_machine.discovery import service


def _app(sources=()):
    return appmod.create_app(
        conn_factory=lambda: MagicMock(),
        client_factory=lambda: MagicMock(),
        sources_loader=lambda: list(sources),
    )


def test_healthz():
    assert TestClient(_app()).get("/healthz").json() == {"status": "ok"}


def test_discover_uses_multi_ats_registry_when_no_body(monkeypatch):
    seen = {}

    def fake(conn, sources):
        seen["sources"] = sources
        return service.DiscoverySummary(boards=len(sources), inserted=5)

    monkeypatch.setattr(service, "run_discovery_multi", fake)
    fake_sources = ["s1", "s2", "s3"]
    resp = TestClient(_app(sources=fake_sources)).post("/discover", json={})
    assert resp.status_code == 200
    assert resp.json()["inserted"] == 5
    assert seen["sources"] == fake_sources


def test_discover_honours_body_boards(monkeypatch):
    seen = {}
    monkeypatch.setattr(service, "run_discovery",
                        lambda conn, client, boards: seen.update(boards=boards)
                        or service.DiscoverySummary())
    TestClient(_app()).post("/discover", json={"boards": ["zeta"]})
    assert seen["boards"] == ["zeta"]


def test_verify_passes_limit(monkeypatch):
    seen = {}
    monkeypatch.setattr(service, "run_verify",
                        lambda conn, client, limit: seen.update(limit=limit)
                        or service.VerifySummary(checked=limit))
    resp = TestClient(_app()).post("/verify", json={"limit": 7})
    assert resp.json()["checked"] == 7
    assert seen["limit"] == 7
