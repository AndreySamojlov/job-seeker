from job_machine.mcp import tools


class FakeConn:
    def commit(self): self.committed = True
    def close(self): pass


def test_get_search_profile_returns_store_result(monkeypatch):
    monkeypatch.setattr(tools.store, "load_search_profile",
                        lambda conn, candidate_id: {"candidate_id": candidate_id,
                                           "roles": ["QA"], "work_mode": ["remote"]})
    out = tools.get_search_profile(FakeConn(), "andrey-s")
    assert out["roles"] == ["QA"]
    assert out["work_mode"] == ["remote"]


def test_update_search_profile_returns_refreshed_profile(monkeypatch):
    monkeypatch.setattr(tools.store, "update_search_profile",
                        lambda conn, patch, candidate_id: None)
    monkeypatch.setattr(tools.store, "load_search_profile",
                        lambda conn, candidate_id: {"candidate_id": candidate_id, "roles": ["QA"]})
    conn = FakeConn()
    result = tools.update_search_profile(conn, {"roles": ["QA"]}, "andrey-s")
    assert result["candidate_id"] == "andrey-s"
    assert result["roles"] == ["QA"]
    assert conn.committed is True
