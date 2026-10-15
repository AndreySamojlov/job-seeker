from job_machine.mcp.fill_worker_client import FillWorkerClient


class _Resp:
    def raise_for_status(self):
        pass

    def json(self):
        return {"pulled": 0, "pre_submit_ready": 0, "blocked": 0, "errors": 0}


class _FakeHttp:
    def __init__(self):
        self.posted = None

    def post(self, path, json=None):
        self.posted = (path, json)
        return _Resp()

    def close(self):
        pass


def test_run_fill_sends_candidate_id_in_body():
    """MCP-клиент кладёт candidate_id в тело POST /fill/run — иначе воркер получает
    только limit и свипает всех кандидатов вместо запрошенного."""
    http = _FakeHttp()
    client = FillWorkerClient(base_url="http://x", http=http)
    client.run_fill(limit=5, candidate_id="daria-b")
    path, body = http.posted
    assert path == "/fill/run"
    assert body["limit"] == 5
    assert body["candidate_id"] == "daria-b"


class _ResumeResp:
    def __init__(self, body):
        self._body = body

    def raise_for_status(self):
        pass

    def json(self):
        return self._body


class _FakeHttpResume:
    def __init__(self, body):
        self._body = body
        self.posted = None

    def post(self, path, json=None):
        self.posted = (path, json)
        return _ResumeResp(self._body)

    def close(self):
        pass


def test_resume_after_handoff_posts_ids_returns_dict():
    http = _FakeHttpResume({"ok": True, "status": "pre_submit_ready"})
    client = FillWorkerClient(base_url="http://x", http=http)
    result = client.resume_after_handoff("app1", "sid1")
    path, body = http.posted
    assert path == "/fill/resume"
    assert body == {"application_id": "app1", "session_id": "sid1"}
    assert result == {"ok": True, "status": "pre_submit_ready"}
