from job_machine.mcp import tools


class FakeCursor:
    def __init__(self, row): self._row = row
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def execute(self, *a): pass
    def fetchone(self): return self._row


class FakeConn:
    def __init__(self, row): self._row = row
    def cursor(self): return FakeCursor(self._row)
    def commit(self): self.committed = True
    def close(self): pass


def test_request_approval_mints_token(monkeypatch):
    conn = FakeConn(("ph1",))  # application.payload_hash
    monkeypatch.setattr(tools.approval_service, "request_approval",
                        lambda conn, application_id, payload_hash, **k: "appr-123")
    out = tools.request_approval(conn, "a1")
    assert out["approval_id"] == "appr-123"
    assert out["payload_hash"] == "ph1"
    assert conn.committed is True


def test_approve_application_sets_approved(monkeypatch):
    conn = FakeConn(None)
    monkeypatch.setattr(tools.approval_store, "approve", lambda conn, application_id: True)
    out = tools.approve_application(conn, "a1")
    assert out["approved"] is True
    assert conn.committed is True
