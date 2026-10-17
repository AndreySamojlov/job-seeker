from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import importlib
import pytest


def test_worker_module_exists():
    assert importlib.util.find_spec("job_machine.fit.worker") is not None


@pytest.fixture
def harness(monkeypatch):
    from job_machine.fit import worker
    state = SimpleNamespace(open=False, commits=0, rollbacks=0, now=datetime(2026, 1, 1, tzinfo=timezone.utc), outcomes=[], claimed=True)
    job = SimpleNamespace(vacancy_id="00000000-0000-0000-0000-000000000001", payload={"snapshot": "original"}, attempts=1)
    class Conn:
        def commit(self): state.commits += 1
        def rollback(self): state.rollbacks += 1
    @contextmanager
    def connect():
        assert not state.open
        state.open = True
        try: yield Conn()
        finally: state.open = False
    def claim(conn, *, now):
        if state.claimed:
            state.claimed = False
            return job
        return None
    def complete(conn, claimed, result, *, now):
        state.outcomes.append(("complete", now, result))
        return now < datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=60)
    def fail(conn, claimed, error, *, now):
        state.outcomes.append(("fail", now, error))
        return True
    monkeypatch.setattr(worker.store, "claim_due", claim)
    monkeypatch.setattr(worker.store, "complete", complete)
    monkeypatch.setattr(worker.store, "fail", fail)
    def evaluate(payload, **kwargs):
        assert not state.open
        assert state.commits == 2
        assert payload == {"snapshot": "original"}
        state.now += timedelta(seconds=3)
        return SimpleNamespace(score=75)
    monkeypatch.setattr(worker, "evaluate_payload", evaluate)
    return worker, state, connect


def run(h, key="synthetic"):
    worker, state, connect = h
    return worker.run_once(connect, client=object(), api_key=key, clock=lambda: state.now, reserve_request=lambda *a, **kw: True)


def test_success_commits_claim_before_http_and_reads_clock_after(harness):
    assert run(harness) == "completed"
    _, state, _ = harness
    assert state.commits == 3
    assert state.outcomes[0][1] == state.now
    assert run(harness) == "idle"


def test_late_response_loses_lease(harness, monkeypatch):
    worker, state, _ = harness
    def late(*a, **kw):
        state.now += timedelta(seconds=61)
        return SimpleNamespace(score=75)
    monkeypatch.setattr(worker, "evaluate_payload", late)
    assert run(harness) == "lease_lost"
    assert state.commits == 2
    assert state.rollbacks == 1


@pytest.mark.parametrize("retryable,code,outcome", [(True,"http_429","retry_wait"),(True,"network_error","retry_wait"),(False,"http_401","blocked")])
def test_expected_failure_is_saved_without_fabricating_score(harness, monkeypatch, retryable, code, outcome):
    worker, state, _ = harness
    from job_machine.fit.models import FitError
    error = FitError(code, retryable=retryable, retry_after_seconds=80 if retryable else None)
    def fail(*a, **kw): raise error
    monkeypatch.setattr(worker, "evaluate_payload", fail)
    assert run(harness) == outcome
    assert state.outcomes[0][0] == "fail"
    assert state.outcomes[0][2] is error


def test_missing_key_blocks_without_http(harness, monkeypatch):
    worker, state, _ = harness
    def forbidden(*a, **kw): pytest.fail("HTTP called without key")
    monkeypatch.setattr(worker, "evaluate_payload", forbidden)
    assert run(harness, " ") == "blocked"
    assert state.outcomes[0][2].code == "missing_api_key"


def test_crash_after_http_does_not_commit_result(harness, monkeypatch):
    worker, state, _ = harness
    def crash(*a, **kw): raise RuntimeError("synthetic database crash")
    monkeypatch.setattr(worker.store, "complete", crash)
    with pytest.raises(RuntimeError): run(harness)
    assert state.commits == 2
    assert not state.open


def test_error_after_expiry_cannot_change_job(harness, monkeypatch):
    worker, state, _ = harness
    from job_machine.fit.models import FitError
    def fail(*args, **kwargs):
        state.now += timedelta(seconds=61)
        raise FitError("network_error", True)
    monkeypatch.setattr(worker, "evaluate_payload", fail)
    monkeypatch.setattr(worker.store, "fail", lambda *args, **kwargs: False)
    assert run(harness) == "lease_lost"
    assert state.commits == 2
    assert state.rollbacks == 1


def test_cli_status_selects_only_safe_columns(monkeypatch, capsys):
    from job_machine.fit import __main__ as cli
    state = {}
    class Conn:
        def execute(self, sql):
            state["sql"] = sql
            return SimpleNamespace(fetchall=lambda: [("pending", 2)])
    @contextmanager
    def connect(): yield Conn()
    monkeypatch.setattr(cli, "connect", connect)
    assert cli.main(["status"]) == 0
    assert "payload" not in state["sql"].lower()
    assert '"pending": 2' in capsys.readouterr().out


def test_cli_error_output_never_contains_exception_detail(monkeypatch, capsys):
    from job_machine.fit import __main__ as cli
    def fail(): raise RuntimeError("secret payload body")
    monkeypatch.setattr(cli, "connect", fail)
    assert cli.main(["status"]) == 1
    output = capsys.readouterr().out
    assert "secret" not in output
    assert "operation_failed" in output


def test_cli_resume_is_explicit_and_uses_store_fencing(monkeypatch, capsys):
    from job_machine.fit import __main__ as cli
    state = {}
    class Conn:
        def commit(self): state["commit"] = True
    @contextmanager
    def connect(): yield Conn()
    monkeypatch.setattr(cli, "connect", connect)
    def rearm(conn, candidate, vacancy, *, now):
        state["candidate"] = candidate
        return False
    monkeypatch.setattr(cli.store, "rearm_blocked", rearm)
    assert cli.main(["resume-blocked", "--candidate-id", "synthetic", "--vacancy-id", "00000000-0000-0000-0000-000000000001"]) == 0
    assert state == {"candidate": "synthetic", "commit": True}
    assert "false" in capsys.readouterr().out


def test_synthetic_probe_requires_explicit_execute(monkeypatch, capsys):
    import runpy
    from pathlib import Path
    probe = runpy.run_path(str(Path(__file__).resolve().parents[2] / "scripts/probe_vacancy_fit.py"))
    def forbidden(*args, **kwargs): pytest.fail("unexpected external request")
    monkeypatch.setattr(probe["httpx"], "Client", forbidden)
    assert probe["main"]([]) == 0
    assert "explicit_execute_required" in capsys.readouterr().out


def test_synthetic_probe_missing_key_is_unverified(monkeypatch, capsys):
    import runpy
    from pathlib import Path
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    probe = runpy.run_path(str(Path(__file__).resolve().parents[2] / "scripts/probe_vacancy_fit.py"))
    def forbidden(*args, **kwargs): pytest.fail("unexpected external request")
    monkeypatch.setattr(probe["httpx"], "Client", forbidden)
    assert probe["main"](["--execute"]) == 1
    assert "missing_api_key" in capsys.readouterr().out


def test_quota_commit_precedes_http(harness, monkeypatch):
    worker, state, connect = harness
    def reserve(conn, **kwargs):
        assert state.open
        assert state.commits == 1
        assert kwargs['now']() == state.now
        return True
    def evaluate(*args, **kwargs):
        assert not state.open
        assert state.commits == 2
        return SimpleNamespace(score=75)
    monkeypatch.setattr(worker, 'evaluate_payload', evaluate)
    assert worker.run_once(connect, client=object(), api_key='synthetic', clock=lambda: state.now, reserve_request=reserve) == 'completed'
    assert state.commits == 3


def test_worker_reserves_again_if_commit_crosses_utc_midnight(harness, monkeypatch):
    worker, state, connect = harness
    state.now = datetime(2026, 1, 1, 23, 59, 59, tzinfo=timezone.utc)
    reservations = []
    monkeypatch.setattr(worker, 'evaluate_payload', lambda *a, **kw: SimpleNamespace(score=75))
    monkeypatch.setattr(worker.store, 'complete', lambda *a, **kw: True)

    def reserve(conn, **kwargs):
        sampled = kwargs['now']()
        reservations.append(sampled)
        if len(reservations) == 1:
            state.now = datetime(2026, 1, 2, 0, 0, 1, tzinfo=timezone.utc)
        return True

    assert worker.run_once(connect, client=object(), api_key='synthetic',
                           clock=lambda: state.now, reserve_request=reserve) == 'completed'
    assert reservations == [
        datetime(2026, 1, 1, 23, 59, 59, tzinfo=timezone.utc),
        datetime(2026, 1, 2, 0, 0, 1, tzinfo=timezone.utc),
    ]
    assert state.commits == 4


def test_exhausted_quota_releases_at_utc_midnight(harness, monkeypatch):
    worker, state, connect = harness
    state.now = datetime(2026, 1, 1, 23, 0, tzinfo=timezone.utc)
    def forbidden(*args, **kwargs): pytest.fail('HTTP called after quota exhaustion')
    monkeypatch.setattr(worker, 'evaluate_payload', forbidden)
    deferred = []
    monkeypatch.setattr(worker.store, 'defer_for_quota', lambda conn, job, **kw: deferred.append(kw) or True, raising=False)
    assert worker.run_once(connect, client=object(), api_key='synthetic', clock=lambda: state.now, reserve_request=lambda *a, **kw: False) == 'quota_exhausted'
    assert deferred == [{'retry_at': datetime(2026, 1, 2, tzinfo=timezone.utc), 'now': state.now}]
    assert state.commits == 2
