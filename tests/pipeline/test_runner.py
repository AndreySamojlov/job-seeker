from job_machine.discovery.sources import SourceSpec
from job_machine.pipeline import runner


class FakeConn:
    def close(self): pass
    def commit(self): pass


def _summary(**kw):
    return type("S", (), kw)()


def test_run_pipeline_happy_path_aggregates_all_stages(monkeypatch):
    calls = []
    monkeypatch.setattr(runner.discovery_service, "run_discovery_multi",
                        lambda conn, specs: calls.append("discover") or
                        _summary(fetched=5, inserted=2, duplicates=1, errors=[]))
    monkeypatch.setattr(runner.discovery_service, "run_verify",
                        lambda conn, client, limit: calls.append("verify") or
                        _summary(checked=2, verified=2, stale=0, transient=0))
    monkeypatch.setattr(runner.package_service, "run_package_build",
                        lambda conn, base_dir, limit, candidate_id=None:
                        calls.append("package") or 1)
    monkeypatch.setattr(runner.fill_service, "run_fill",
                        lambda conn, browser, limit, candidate_id=None:
                        calls.append("fill") or _summary(pre_submit_ready=1))

    out = runner.run_pipeline(FakeConn(), greenhouse_client=object(),
                              browser=object(), boards=["acme"])

    assert calls == ["discover", "verify", "package", "fill"]
    assert out["stopped_at"] is None
    assert out["error"] is None
    assert out["discovery"]["inserted"] == 2
    assert out["verify"]["verified"] == 2
    assert out["package"]["built"] == 1
    assert out["fill"]["pre_submit_ready"] == 1


def test_run_pipeline_stops_on_package_failure(monkeypatch):
    """Package бросает исключение → fill не вызывается, discovery/verify сохранены."""
    calls = []
    monkeypatch.setattr(runner.discovery_service, "run_discovery_multi",
                        lambda conn, specs: calls.append("discover") or
                        _summary(fetched=1, inserted=1, duplicates=0, errors=[]))
    monkeypatch.setattr(runner.discovery_service, "run_verify",
                        lambda conn, client, limit: calls.append("verify") or
                        _summary(checked=1, verified=1, stale=0, transient=0))

    def _boom(conn, base_dir, limit, candidate_id=None):
        calls.append("package")
        raise RuntimeError("db unreachable")

    monkeypatch.setattr(runner.package_service, "run_package_build", _boom)
    monkeypatch.setattr(runner.fill_service, "run_fill",
                        lambda conn, browser, limit, candidate_id=None:
                        calls.append("fill") or _summary(pre_submit_ready=1))

    out = runner.run_pipeline(FakeConn(), greenhouse_client=object(),
                              browser=object(), boards=["acme"])

    assert calls == ["discover", "verify", "package"]
    assert out["stopped_at"] == "package"
    assert "db unreachable" in out["error"]
    assert out["discovery"] is not None
    assert out["verify"] is not None
    assert out["package"] is None
    assert out["fill"] is None


def test_run_pipeline_stops_on_first_stage_failure(monkeypatch):
    """Discovery бросает исключение первой → все остальные стадии None."""
    def _boom(conn, specs):
        raise RuntimeError("board fetch failed")

    monkeypatch.setattr(runner.discovery_service, "run_discovery_multi", _boom)

    out = runner.run_pipeline(FakeConn(), greenhouse_client=object(),
                              browser=object(), boards=["acme"])

    assert out["stopped_at"] == "discovery"
    assert out["discovery"] is None
    assert out["verify"] is None
    assert out["package"] is None
    assert out["fill"] is None


def test_run_pipeline_fill_skipped_without_worker_or_browser(monkeypatch):
    monkeypatch.setattr(runner.discovery_service, "run_discovery_multi",
                        lambda conn, specs: _summary(fetched=0, inserted=0, duplicates=0, errors=[]))
    monkeypatch.setattr(runner.discovery_service, "run_verify",
                        lambda conn, client, limit: _summary(checked=0, verified=0, stale=0, transient=0))
    monkeypatch.setattr(runner.package_service, "run_package_build",
                        lambda conn, base_dir, limit, candidate_id=None: 0)

    out = runner.run_pipeline(FakeConn(), greenhouse_client=object(), boards=["acme"])

    assert out["stopped_at"] is None
    assert out["fill"] == {"pre_submit_ready": 0, "skipped": True}


def test_run_pipeline_uses_package_worker_when_provided(monkeypatch):
    """package_worker передан → делегируем ему, local package_service не трогаем
    (local пишет нечитаемые lab-do пути на Windows, см. mcp/package_worker_client.py)."""
    calls = []
    monkeypatch.setattr(runner.discovery_service, "run_discovery_multi",
                        lambda conn, specs: _summary(fetched=0, inserted=0, duplicates=0, errors=[]))
    monkeypatch.setattr(runner.discovery_service, "run_verify",
                        lambda conn, client, limit: _summary(checked=0, verified=0, stale=0, transient=0))

    def _local_boom(conn, base_dir, limit, candidate_id=None):
        calls.append("local_package")
        raise AssertionError("local package_service must not be called when package_worker is given")

    monkeypatch.setattr(runner.package_service, "run_package_build", _local_boom)

    class _PackageWorker:
        def run_package_build(self, limit=10, candidate_id=None):
            calls.append("worker_package")
            return 7

    out = runner.run_pipeline(FakeConn(), greenhouse_client=object(),
                              package_worker=_PackageWorker(), boards=["acme"])

    assert calls == ["worker_package"]
    assert out["package"]["built"] == 7
    assert out["fill"] == {"pre_submit_ready": 0, "skipped": True}


def test_run_pipeline_forwards_candidate_id_to_package_and_fill(monkeypatch):
    """candidate_id прокидывается в package- и fill-стадии (скоуп очереди per-кандидат)."""
    captured = {}
    monkeypatch.setattr(runner.discovery_service, "run_discovery_multi",
                        lambda conn, specs: _summary(fetched=0, inserted=0,
                                                     duplicates=0, errors=[]))
    monkeypatch.setattr(runner.discovery_service, "run_verify",
                        lambda conn, client, limit: _summary(checked=0, verified=0,
                                                             stale=0, transient=0))
    monkeypatch.setattr(runner.package_service, "run_package_build",
                        lambda conn, base_dir, limit, candidate_id=None:
                        captured.__setitem__("pkg", candidate_id) or 0)

    class _Worker:
        def run_fill(self, limit=10, candidate_id=None):
            captured["fill"] = candidate_id
            return _summary(pre_submit_ready=0)

    runner.run_pipeline(FakeConn(), greenhouse_client=object(),
                        fill_worker=_Worker(), boards=["acme"], candidate_id="daria-b")
    assert captured["pkg"] == "daria-b"
    assert captured["fill"] == "daria-b"


def test_run_pipeline_excludes_browser_backed_ats_from_default_load_sources(monkeypatch):
    """Баг: load_sources() (дефолтная ветка, без явных sources/boards) отдавала hh
    вперемешку с httpx-бордами — как только пагинация доходила до хвоста
    sources.json, дешёвый частый цикл начинал инлайново дёргать
    Playwright-backed HhClient (риск OOM browser-worker, см. финальный ревью
    среза hh-ru-sourcing). load_sources() должна фильтроваться, специфичные
    ``sources``/``boards`` — нет (это покрыто другими тестами в этом файле)."""
    monkeypatch.setattr(runner, "load_sources", lambda: [
        SourceSpec(ats="greenhouse", token="acme"),
        SourceSpec(ats="hh", token="qa-lead", query={"text": "QA Lead"}),
    ])
    captured = {}
    monkeypatch.setattr(runner.discovery_service, "run_discovery_multi",
                        lambda conn, specs: captured.__setitem__("page", specs) or
                        _summary(fetched=0, inserted=0, duplicates=0, errors=[]))
    monkeypatch.setattr(runner.discovery_service, "run_verify",
                        lambda conn, client, limit: _summary(checked=0, verified=0,
                                                             stale=0, transient=0))
    monkeypatch.setattr(runner.package_service, "run_package_build",
                        lambda conn, base_dir, limit, candidate_id=None: 0)

    runner.run_pipeline(FakeConn(), greenhouse_client=object())

    assert [s.ats for s in captured["page"]] == ["greenhouse"]
