from job_machine.package import service
from job_machine.package.models import AnswerRecord, ResumeArtifact


class _FakeConn:
    def commit(self): pass


def test_run_package_build_merges_per_app_answers(monkeypatch):
    captured = {}
    monkeypatch.setattr(service.store, "load_answers",
                        lambda conn, candidate_id: [AnswerRecord(field="Preferred location",
                                                   value="Anywhere", state="locked")])
    monkeypatch.setattr(service.store, "load_application_answers",
                        lambda conn, aid: [AnswerRecord(field="Preferred location",
                                                        value="Remote, Germany", state="locked")])
    monkeypatch.setattr(service.provenance, "answers_version",
                        lambda answers: captured.update({"version_input": answers}) or "v1")
    monkeypatch.setattr(service.store, "pull_needs_package",
                        lambda conn, limit, candidate_id=None: [{"application_id": "a1", "company": "Acme",
                                              "role": "QA", "destination_url": "https://a/1",
                                              "ats_family": "greenhouse", "fit_summary": "",
                                              "hard_requirements": [], "candidate_id": "andrey-s"}])
    monkeypatch.setattr(service.artifacts, "select_resume",
                        lambda conn, aid: ResumeArtifact(filename="r.pdf", path="/r.pdf",
                                                         content_hash="h"))

    def _fake_build(inp, answers, resume):
        captured["answers"] = answers
        return "MANIFEST"

    monkeypatch.setattr(service, "build_package", _fake_build)
    monkeypatch.setattr(service.artifacts, "write_artifacts", lambda base, m, s: [])
    monkeypatch.setattr(service, "render_summary", lambda m: "")
    monkeypatch.setattr(service.store, "record_package",
                        lambda conn, m, descs, answers_version=None: None)

    built = service.run_package_build(_FakeConn(), "applications", limit=5)
    assert built == 1
    vals = {a.field: a.value for a in captured["answers"]}
    assert vals["Preferred location"] == "Remote, Germany"
    # answers_version провенансится от merged (включая per-app override), не от global
    version_vals = {a.field: a.value for a in captured["version_input"]}
    assert version_vals["Preferred location"] == "Remote, Germany"
