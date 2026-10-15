from job_machine.discovery.sources import SourceSpec
from job_machine.mcp import tools
from job_machine.fill.models import FillRunSummary


class FakeConn:
    def close(self): pass


class FakeFillWorker:
    def __init__(self, summary=None):
        self._summary = summary or FillRunSummary(pre_submit_ready=1)
        self.last_candidate_id = "UNSET"

    def run_fill(self, limit=10, candidate_id=None):
        self.last_candidate_id = candidate_id
        return self._summary

    def close(self): pass


def test_run_pipeline_tool_delegates(monkeypatch):
    monkeypatch.setattr(tools.pipeline_runner, "run_pipeline",
                        lambda conn, greenhouse_client, fill_worker, boards, **k:
                        {"discovery": {"inserted": 3}, "verify": None, "package": None,
                         "fill": None, "stopped_at": None, "error": None})
    out = tools.run_pipeline(FakeConn(), greenhouse_client=object(),
                             fill_worker=FakeFillWorker(), boards=["acme"])
    assert out["discovery"]["inserted"] == 3


def test_run_pipeline_passes_max_boards_and_offset(monkeypatch):
    captured = {}

    def fake_runner(conn, greenhouse_client, fill_worker=None, boards=None, **k):
        captured.update(k)
        return {"discovery": None, "verify": None, "package": None,
                "fill": None, "stopped_at": None, "error": None}

    monkeypatch.setattr(tools.pipeline_runner, "run_pipeline", fake_runner)
    tools.run_pipeline(FakeConn(), greenhouse_client=object(),
                       max_boards=5, offset=2, limit=7)
    assert captured["max_boards"] == 5
    assert captured["offset"] == 2
    assert captured["limit"] == 7


def test_run_pipeline_passes_base_dir(monkeypatch):
    """PACKAGE_BASE_DIR должен совпадать между run_pipeline и standalone run_package —
    иначе оператор получит расхождение в том, куда пишутся пакеты (найдено финальным
    ревью среза run-pipeline-blocking-fix)."""
    captured = {}

    def fake_runner(conn, greenhouse_client, fill_worker=None, boards=None, **k):
        captured.update(k)
        return {"discovery": None, "verify": None, "package": None,
                "fill": None, "stopped_at": None, "error": None}

    monkeypatch.setattr(tools.pipeline_runner, "run_pipeline", fake_runner)
    tools.run_pipeline(FakeConn(), greenhouse_client=object(), base_dir="/data/candidate-x")
    assert captured["base_dir"] == "/data/candidate-x"


def test_run_pipeline_passes_package_worker(monkeypatch):
    """package_worker прокидывается в pipeline_runner — иначе run_pipeline тихо
    падает обратно на local package_service (пишет нечитаемые lab-do пути)."""
    captured = {}

    def fake_runner(conn, greenhouse_client, fill_worker=None, boards=None, **k):
        captured.update(k)
        return {"discovery": None, "verify": None, "package": None,
                "fill": None, "stopped_at": None, "error": None}

    monkeypatch.setattr(tools.pipeline_runner, "run_pipeline", fake_runner)
    worker = FakePackageWorker()
    tools.run_pipeline(FakeConn(), greenhouse_client=object(), package_worker=worker)
    assert captured["package_worker"] is worker


def test_run_discovery_slices_sources(monkeypatch):
    specs = [SourceSpec(ats="greenhouse", token=f"b{i}") for i in range(5)]
    captured = {}

    def fake_multi(conn, page):
        captured["page"] = [s.token for s in page]
        return type("S", (), {"fetched": 1, "inserted": 1, "duplicates": 0, "errors": []})()

    monkeypatch.setattr(tools.discovery_service, "run_discovery_multi", fake_multi)

    out = tools.run_discovery(FakeConn(), max_boards=2, offset=1, sources=specs)

    assert captured["page"] == ["b1", "b2"]
    assert out["boards_processed"] == 2
    assert out["boards_total"] == 5
    assert out["next_offset"] == 3
    assert out["inserted"] == 1


def test_run_discovery_default_load_sources_excludes_browser_backed_ats(monkeypatch):
    """Баг: дефолтная ветка (sources не передан) грузила load_sources() без
    фильтра — hh (Playwright/browser-worker-backed) мог попасть в дешёвый частый
    MCP discovery-цикл, как только пагинация доходила до хвоста sources.json
    (риск OOM browser-worker, финальный ревью среза hh-ru-sourcing)."""
    specs = [
        SourceSpec(ats="greenhouse", token="acme"),
        SourceSpec(ats="hh", token="qa-lead", query={"text": "QA Lead"}),
    ]
    monkeypatch.setattr(tools, "load_sources", lambda: specs)
    captured = {}

    def fake_multi(conn, page):
        captured["page"] = [s.ats for s in page]
        return type("S", (), {"fetched": 0, "inserted": 0, "duplicates": 0, "errors": []})()

    monkeypatch.setattr(tools.discovery_service, "run_discovery_multi", fake_multi)

    tools.run_discovery(FakeConn(), max_boards=10, offset=0)

    assert captured["page"] == ["greenhouse"]


def test_run_discovery_explicit_sources_are_not_filtered(monkeypatch):
    """Явно переданный sources (напр. будущий hh-only cron-вызов) должен
    проходить как есть — фильтр browser-backed ATS применяется ТОЛЬКО к
    дефолтной ветке load_sources(), не к явному аргументу вызывающего."""
    specs = [SourceSpec(ats="hh", token="qa-lead", query={"text": "QA Lead"})]
    captured = {}

    def fake_multi(conn, page):
        captured["page"] = [s.ats for s in page]
        return type("S", (), {"fetched": 0, "inserted": 0, "duplicates": 0, "errors": []})()

    monkeypatch.setattr(tools.discovery_service, "run_discovery_multi", fake_multi)

    tools.run_discovery(FakeConn(), max_boards=10, offset=0, sources=specs)

    assert captured["page"] == ["hh"]


def test_run_verify_wraps_summary(monkeypatch):
    monkeypatch.setattr(tools.discovery_service, "run_verify",
                        lambda conn, client, limit: type(
                            "S", (), {"checked": 2, "verified": 1, "stale": 1, "transient": 0})())
    out = tools.run_verify(FakeConn(), client=object(), limit=5)
    assert out == {"checked": 2, "verified": 1, "stale": 1, "transient": 0}


class FakePackageWorker:
    def __init__(self, built=0):
        self._built = built
        self.last_candidate_id = "UNSET"
        self.last_limit = "UNSET"

    def run_package_build(self, limit=10, candidate_id=None):
        self.last_candidate_id = candidate_id
        self.last_limit = limit
        return self._built

    def close(self): pass


def test_run_package_wraps_count():
    out = tools.run_package(FakePackageWorker(built=4), limit=10)
    assert out == {"built": 4}


def test_run_package_passes_candidate_id():
    worker = FakePackageWorker()
    tools.run_package(worker, limit=10, candidate_id="daria-b")
    assert worker.last_candidate_id == "daria-b"


def test_run_fill_wraps_summary():
    worker = FakeFillWorker(FillRunSummary(pulled=3, pre_submit_ready=2, blocked=1, errors=0))
    out = tools.run_fill(worker, limit=10)
    assert out == {"pulled": 3, "pre_submit_ready": 2, "blocked": 1, "errors": 0}


def test_run_fill_passes_candidate_id():
    worker = FakeFillWorker()
    tools.run_fill(worker, limit=10, candidate_id="daria-b")
    assert worker.last_candidate_id == "daria-b"


def test_run_pipeline_tool_passes_candidate_id(monkeypatch):
    captured = {}

    def fake_runner(conn, greenhouse_client, fill_worker=None, boards=None, **k):
        captured.update(k)
        return {"discovery": None, "verify": None, "package": None,
                "fill": None, "stopped_at": None, "error": None}

    monkeypatch.setattr(tools.pipeline_runner, "run_pipeline", fake_runner)
    tools.run_pipeline(FakeConn(), greenhouse_client=object(), candidate_id="daria-b")
    assert captured["candidate_id"] == "daria-b"


def test_stage_tools_pass_through_limit_zero(monkeypatch):
    """limit=0 — валидный ввод, тулы не подставляют дефолт и не ошибаются."""
    captured = {}
    monkeypatch.setattr(tools.discovery_service, "run_verify",
                        lambda conn, client, limit: captured.setdefault("verify_limit", limit) or
                        type("S", (), {"checked": 0, "verified": 0, "stale": 0, "transient": 0})())
    worker = FakePackageWorker()

    tools.run_verify(FakeConn(), client=object(), limit=0)
    tools.run_package(worker, limit=0)

    assert captured["verify_limit"] == 0
    assert worker.last_limit == 0
