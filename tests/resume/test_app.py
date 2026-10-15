from fastapi.testclient import TestClient

from job_machine.resume.app import create_app


def test_healthz_and_no_submit_route():
    app = create_app(conn_factory=lambda: None, pdf_factory=lambda: None)
    with TestClient(app) as client:
        assert client.get("/healthz").json() == {"status": "ok"}
    routes = {r.path for r in app.routes}
    assert "/resume/pull" in routes and "/resume/apply" in routes and "/resume/run" in routes
    assert "/submit" not in routes


def test_pull_returns_phrasing_requests(monkeypatch):
    import job_machine.resume.app as appmod

    class _Conn:
        def close(self):
            pass

    monkeypatch.setattr(appmod.store, "pull_needs_resume",
                        lambda conn, limit: [{"application_id": "a1", "role": "QA Lead",
                                              "hard_requirements": [], "candidate_id": "andrey-s",
                                              "candidate_name": "Andrey Samoylov"}])
    monkeypatch.setattr(appmod, "load_cloud", lambda conn, candidate_id: _cloud())
    app = create_app(conn_factory=_Conn, pdf_factory=lambda: None)
    with TestClient(app) as client:
        body = client.post("/resume/pull", json={"limit": 5}).json()
    assert body["count"] == 1
    assert body["items"][0]["application_id"] == "a1"
    assert "bullets" in body["items"][0]


def _cloud():
    from job_machine.cloud.models import (
        CloudAchievement, CloudPosition, CloudSkill, ExperienceCloud,
    )
    return ExperienceCloud(
        positions=[CloudPosition(pid="P-01", company="NSD", title="Head of QA",
                                 start="2024-09", end="present")],
        achievements=[CloudAchievement(aid="A-04", pid="P-01", text="Throughput", metric="x")],
        skills=[CloudSkill(name="QA", category="skill", framing="Expert")])


def test_apply_invokes_service(monkeypatch):
    import job_machine.resume.app as appmod
    seen = {}

    class _Conn:
        def close(self):
            seen["closed"] = True

    def _apply(conn, pdf, base_dir, phrasing):
        seen["app_id"] = phrasing.application_id
        from job_machine.package.models import ResumeArtifact
        return ResumeArtifact(filename="r.pdf", path="/d/r.pdf", content_hash="h")

    monkeypatch.setattr(appmod.service, "apply_phrasing", _apply)
    app = create_app(conn_factory=_Conn, pdf_factory=lambda: object())
    with TestClient(app) as client:
        resp = client.post("/resume/apply",
                           json={"application_id": "a1", "bullets": [{"aid": "A-04",
                                 "phrased_text": "x"}]})
    assert resp.json()["content_hash"] == "h"
    assert seen["app_id"] == "a1" and seen["closed"]
