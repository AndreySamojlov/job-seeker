from job_machine.mcp import tools


class FakeConn:
    def commit(self): self.committed = True
    def close(self): pass


def test_list_telegram_leads_delegates_to_store(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        tools, "telegram_store",
        type("M", (), {"load_new_for_triage": staticmethod(
            lambda conn, candidate_id, limit: captured.update(
                candidate_id=candidate_id, limit=limit) or
            [{"lead_id": "l1", "channel": "forallqa", "raw_text": "QA remote"}]
        )}),
    )
    out = tools.list_telegram_leads(FakeConn(), candidate_id="andrey-s", limit=5)
    assert captured["candidate_id"] == "andrey-s"
    assert captured["limit"] == 5
    assert out == [{"lead_id": "l1", "channel": "forallqa", "raw_text": "QA remote"}]


def test_triage_telegram_lead_writes_verdict_and_commits(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        tools, "telegram_store",
        type("M", (), {"apply_triage_verdict": staticmethod(
            lambda conn, lead_id, candidate_id, is_relevant, extracted:
            captured.update(lead_id=lead_id, candidate_id=candidate_id,
                            is_relevant=is_relevant, extracted=extracted)
        )}),
    )
    conn = FakeConn()
    out = tools.triage_telegram_lead(
        conn, candidate_id="andrey-s", lead_id="l1", is_relevant=True,
        role_title="QA Engineer", company="Acme", location="Cyprus",
        work_mode="remote", apply_hint="DM @hr_acme", note="strong fit",
    )
    assert captured["lead_id"] == "l1"
    assert captured["candidate_id"] == "andrey-s"
    assert captured["is_relevant"] is True
    assert captured["extracted"] == {
        "role_title": "QA Engineer", "company": "Acme", "location": "Cyprus",
        "work_mode": "remote", "apply_hint": "DM @hr_acme", "note": "strong fit",
    }
    assert conn.committed is True
    assert out == {"lead_id": "l1", "triaged": True}
