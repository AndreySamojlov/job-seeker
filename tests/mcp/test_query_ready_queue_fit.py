from job_machine.mcp import store


class _FakeCursor:
    def __init__(self, rows, cols):
        self._rows, self.description = rows, [type("C", (), {"name": c}) for c in cols]
    def execute(self, *a, **k): pass
    def fetchall(self): return self._rows
    def __enter__(self): return self
    def __exit__(self, *a): return False


class _FakeConn:
    def __init__(self, rows, cols): self._rows, self._cols = rows, cols
    def cursor(self): return _FakeCursor(self._rows, self._cols)


def test_query_ready_queue_sorts_by_fit_desc_nulls_last():
    cols = ["application_id", "company", "role", "url", "status", "payload_hash",
            "screenshot_path", "fit_score", "fit_band"]
    rows = [
        ("a1", "Acme", "QA", "u", "pre_submit_ready", "h", None, 40, "C"),
        ("a2", "Beta", "QA", "u", "pre_submit_ready", "h", None, 88, "A"),
        ("a3", "Cira", "QA", "u", "pre_submit_ready", "h", None, None, None),
    ]
    conn = _FakeConn(rows, cols)
    out = store.query_ready_queue(conn, "andrey-s", 20)
    assert [r["application_id"] for r in out] == ["a2", "a1", "a3"]  # 88 > 40 > NULL
    assert out[0]["fit_band"] == "A" and out[0]["fit_score"] == 88
