from job_machine.mcp import tools


class _FakeConn:
    def commit(self): pass
    def close(self): pass


def test_set_application_answers_stores_locked(monkeypatch):
    captured = {}
    monkeypatch.setattr(tools.package_store, "upsert_application_answers",
                        lambda conn, aid, recs: captured.update({"aid": aid, "recs": recs}))
    out = tools.set_application_answers(_FakeConn(), "a1",
                                       [{"field": "Preferred location", "value": "Remote, Germany"}])
    assert out["saved"] == 1
    assert captured["recs"][0].state == "locked"
    assert captured["recs"][0].value == "Remote, Germany"


def test_set_application_answers_rejects_consent(monkeypatch):
    captured = {"recs": None}
    monkeypatch.setattr(tools.package_store, "upsert_application_answers",
                        lambda conn, aid, recs: captured.update({"recs": recs}))
    out = tools.set_application_answers(_FakeConn(), "a1", [
        {"field": "Preferred location", "value": "Remote, Germany"},
        {"field": "Please review our Privacy Notice before submitting", "value": "Confirm"},
        {"field": "I agree to the terms and conditions", "value": "Yes"},
    ])
    assert out["saved"] == 1  # только не-consent
    assert len(out["rejected"]) == 2
    stored_fields = [r.field for r in captured["recs"]]
    assert stored_fields == ["Preferred location"]


def test_set_application_answers_allows_work_auth(monkeypatch):
    # work-auth — отвечаемый факт владельца, НЕ consent: не должен отклоняться
    captured = {"recs": None}
    monkeypatch.setattr(tools.package_store, "upsert_application_answers",
                        lambda conn, aid, recs: captured.update({"recs": recs}))
    out = tools.set_application_answers(_FakeConn(), "a1",
        [{"field": "Are you authorised to work in Bulgaria?", "value": "No"}])
    assert out["saved"] == 1
    assert out["rejected"] == []


def test_regenerate_resume_delegates(monkeypatch):
    monkeypatch.setattr(tools.regen, "reopen_for_regen",
                        lambda conn, aid: {"ok": True, "application_id": aid})
    assert tools.regenerate_resume(_FakeConn(), "a1")["ok"] is True


def test_prepare_application_answers_filters_answered_and_identity(monkeypatch):
    monkeypatch.setattr(tools.mcp_store, "load_application_source",
                        lambda conn, aid: {"source_url": "https://x/jobs/1",
                                           "ats_family": "greenhouse",
                                           "candidate_id": "cand-1"})
    captured = {}

    def _fake_load_answers(conn, candidate_id):
        captured["candidate_id"] = candidate_id
        return []

    monkeypatch.setattr(tools.package_store, "load_answers", _fake_load_answers)
    monkeypatch.setattr(tools.package_store, "load_application_answers", lambda conn, aid: [])
    fake_questions = [
        {"label": "First Name", "required": True, "fields": ["first_name"], "options": []},
        {"label": "Resume/CV", "required": True, "fields": ["resume"], "options": []},
        {"label": "Which is your preferred location for this role?", "required": True,
         "fields": ["question_1[]"], "options": ["Remote, Germany", "Berlin"]},
        {"label": "Cover Letter", "required": False, "fields": ["cover_letter"], "options": []},
    ]
    out = tools.prepare_application_answers(_FakeConn(), "a1",
                                           fetcher=lambda url: fake_questions)
    labels = [q["label"] for q in out]
    assert "Which is your preferred location for this role?" in labels
    assert "First Name" not in labels
    assert "Resume/CV" not in labels
    assert "Cover Letter" not in labels
    # load_answers должен быть вызван с candidate_id заявки, а не глобально
    assert captured["candidate_id"] == "cand-1"
