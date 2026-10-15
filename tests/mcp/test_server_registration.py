import asyncio

import pytest


def test_server_exposes_expected_tools():
    from job_machine.mcp.server import mcp
    names = {t.name for t in asyncio.run(mcp.list_tools())}
    expected = {
        "list_candidates", "get_search_profile", "update_search_profile", "list_ready",
        "get_application", "request_approval", "approve_application",
        "submit_application", "record_outcome", "funnel_stats", "run_pipeline",
        "run_discovery", "run_verify", "run_package", "run_fill",
        "handoff_browser", "resume_fill",
        "get_submit_control", "set_submit_control",
    }
    assert expected.issubset(names)


class _FakeConn:
    def close(self):
        pass


class _FakeFillWorker:
    def close(self):
        pass


class _FakePackageWorker:
    def close(self):
        pass


# §6-шов: MCP-обёртки — фактический код, который дёргает ассистент. Change сделал
# candidate_id обязательным именно тут; без этих тестов регрессия, роняющая проброс
# или вернувшая дефолт None, прошла бы CI и молча вернула cross-candidate-баг.
def test_run_package_tool_forwards_candidate_id(monkeypatch):
    from job_machine.mcp import server
    captured = {}
    monkeypatch.setattr(server, "_package_worker", lambda: _FakePackageWorker())
    monkeypatch.setattr(server.tools, "run_package",
                        lambda package_worker, limit, candidate_id:
                        captured.update(candidate_id=candidate_id) or {"built": 0})
    server.run_package(candidate_id="daria-b", limit=5)
    assert captured["candidate_id"] == "daria-b"


def test_run_fill_tool_forwards_candidate_id(monkeypatch):
    from job_machine.mcp import server
    captured = {}
    monkeypatch.setattr(server, "_fill_worker", lambda: _FakeFillWorker())
    monkeypatch.setattr(server.tools, "run_fill",
                        lambda fill_worker, limit, candidate_id:
                        captured.update(candidate_id=candidate_id) or {"pulled": 0})
    server.run_fill(candidate_id="daria-b", limit=5)
    assert captured["candidate_id"] == "daria-b"


def test_run_pipeline_tool_forwards_candidate_id(monkeypatch):
    from job_machine.mcp import server
    captured = {}
    monkeypatch.setattr(server, "connect", lambda: _FakeConn())
    monkeypatch.setattr(server, "_fill_worker", lambda: _FakeFillWorker())
    monkeypatch.setattr(server.tools, "run_pipeline",
                        lambda conn, client, **k:
                        captured.update(k) or {"discovery": None, "stopped_at": None,
                                               "error": None})
    server.run_pipeline(candidate_id="daria-b")
    assert captured["candidate_id"] == "daria-b"


def test_scoped_tools_require_candidate_id():
    """candidate_id ОБЯЗАТЕЛЕН на скоуп-инструментах — защита от возврата к глобальному
    FIFO (корень cross-candidate-бага)."""
    from job_machine.mcp import server
    with pytest.raises(TypeError):
        server.run_package(limit=5)
    with pytest.raises(TypeError):
        server.run_fill(limit=5)
    with pytest.raises(TypeError):
        server.run_pipeline()


def test_resume_fill_tool_delegates_to_tools(monkeypatch):
    from job_machine.mcp import server
    captured = {}

    class _FakeConn2:
        def close(self):
            pass

    monkeypatch.setattr(server, "connect", lambda: _FakeConn2())
    monkeypatch.setattr(server, "_fill_worker", lambda: _FakeFillWorker())
    monkeypatch.setattr(server.tools, "resume_fill",
                        lambda conn, fill_worker, application_id:
                        captured.update(application_id=application_id) or
                        {"ok": True, "status": "pre_submit_ready"})
    result = server.resume_fill(application_id="app1")
    assert captured["application_id"] == "app1"
    assert result == {"ok": True, "status": "pre_submit_ready"}
