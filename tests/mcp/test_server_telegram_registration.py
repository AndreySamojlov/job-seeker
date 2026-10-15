import asyncio


def test_server_exposes_telegram_tools():
    from job_machine.mcp.server import mcp
    names = {t.name for t in asyncio.run(mcp.list_tools())}
    assert {"list_telegram_leads", "triage_telegram_lead"}.issubset(names)


def test_list_telegram_leads_tool_delegates_to_tools(monkeypatch):
    from job_machine.mcp import server

    class _FakeConn:
        def close(self): pass

    monkeypatch.setattr(server, "connect", lambda: _FakeConn())
    monkeypatch.setattr(
        server.tools, "list_telegram_leads",
        lambda conn, candidate_id, limit: [{"lead_id": "l1"}]
        if candidate_id == "andrey-s" and limit == 5 else [],
    )
    assert server.list_telegram_leads(candidate_id="andrey-s", limit=5) == [{"lead_id": "l1"}]


def test_triage_telegram_lead_tool_delegates_to_tools(monkeypatch):
    from job_machine.mcp import server

    class _FakeConn:
        def close(self): pass

    captured = {}
    monkeypatch.setattr(server, "connect", lambda: _FakeConn())
    monkeypatch.setattr(
        server.tools, "triage_telegram_lead",
        lambda conn, **kw: captured.update(kw) or {"lead_id": kw["lead_id"], "triaged": True},
    )
    out = server.triage_telegram_lead(candidate_id="andrey-s", lead_id="l1",
                                       is_relevant=True, role_title="QA")
    assert captured["candidate_id"] == "andrey-s"
    assert captured["lead_id"] == "l1"
    assert captured["role_title"] == "QA"
    assert out == {"lead_id": "l1", "triaged": True}
