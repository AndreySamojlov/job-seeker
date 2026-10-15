from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from job_machine.triage import app as appmod
from job_machine.triage import service
from job_machine.triage.models import TriageInput


def _app():
    return appmod.create_app(conn_factory=lambda: MagicMock(),
                             client_factory=lambda: MagicMock())


def test_healthz():
    assert TestClient(_app()).get("/healthz").json() == {"status": "ok"}


def test_no_submit_route():
    routes = {r.path for r in _app().routes}
    assert "/triage/pull" in routes and "/triage/apply" in routes
    assert not any("submit" in r for r in routes)


def test_pull_returns_inputs(monkeypatch):
    def fake(conn, client, candidate_id, limit):
        return service.PullSummary(
            inputs=[TriageInput(vacancy_id="v1", job_text="t", claims=[])],
            quick_skipped=2,
        )
    monkeypatch.setattr(service, "build_triage_inputs", fake)
    resp = TestClient(_app()).post("/triage/pull", json={"limit": 5})
    body = resp.json()
    assert body["count"] == 1
    assert body["quick_skipped"] == 2
    assert body["inputs"][0]["vacancy_id"] == "v1"


def test_apply_validates_and_routes(monkeypatch):
    seen = {}
    monkeypatch.setattr(service, "apply_triage",
                        lambda conn, verdict, candidate_id: seen.update(
                            vid=verdict.vacancy_id, candidate_id=candidate_id)
                        or "needs_package")
    resp = TestClient(_app()).post("/triage/apply", json={
        "vacancy_id": "v9", "verdict": "apply", "fit_summary": "ok",
        "hard_requirements": [{"requirement": "q", "status": "strong"}]})
    assert resp.json() == {"vacancy_id": "v9", "route": "needs_package"}
    assert seen["vid"] == "v9"
    assert seen["candidate_id"] == "andrey-s"


def test_apply_rejects_bad_payload():
    resp = TestClient(_app()).post("/triage/apply", json={"vacancy_id": "v",
                                                          "verdict": "maybe"})
    assert resp.status_code == 422
