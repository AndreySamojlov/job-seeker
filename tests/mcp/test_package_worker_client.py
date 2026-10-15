from job_machine.mcp.package_worker_client import PackageWorkerClient


class _Resp:
    def __init__(self, built=0):
        self._built = built

    def raise_for_status(self):
        pass

    def json(self):
        return {"built": self._built}


class _FakeHttp:
    def __init__(self, built=0):
        self.posted = None
        self._built = built

    def post(self, path, json=None):
        self.posted = (path, json)
        return _Resp(self._built)

    def close(self):
        pass


def test_run_package_build_sends_candidate_id_in_body():
    """MCP-клиент кладёт candidate_id в тело POST /package/build — иначе воркер
    получает только limit и свипает всех кандидатов вместо запрошенного."""
    http = _FakeHttp()
    client = PackageWorkerClient(base_url="http://x", http=http)
    client.run_package_build(limit=5, candidate_id="daria-b")
    path, body = http.posted
    assert path == "/package/build"
    assert body["limit"] == 5
    assert body["candidate_id"] == "daria-b"


def test_run_package_build_returns_built_count():
    http = _FakeHttp(built=4)
    client = PackageWorkerClient(base_url="http://x", http=http)
    out = client.run_package_build(limit=10, candidate_id="andrey-s")
    assert out == 4
