from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4

import pytest

# The source package is still pinned to the pre-RWR wheel during parallel task
# development. These unit shims disappear when Task 5 installs the API.
import cockpit_engine.rules as engine_rules
if not hasattr(engine_rules, "load_external_decision"):
    from types import SimpleNamespace
    def _load(catalog, code):
        entry = catalog["external_decisions"][code]
        if entry.get("enabled") is not True:
            raise ValueError("disabled")
        return SimpleNamespace(code=code, **{k: entry[k] for k in ("handler", "version", "config")})
    def _invoke(decision, state, *, handlers):
        return handlers[decision.handler](decision, state)
    engine_rules.load_external_decision = _load
    engine_rules.invoke_external_decision = _invoke

from job_machine.remote_readiness import worker

NOW = datetime(2030, 1, 1, tzinfo=timezone.utc)


@dataclass(frozen=True)
class Job:
    vacancy_id: object = field(default_factory=uuid4)
    payload: dict | None = None
    payload_hash: str = "a" * 64
    lease_token: object = field(default_factory=uuid4)
    attempts: int = 1

    def __post_init__(self):
        if self.payload is None:
            object.__setattr__(self, "payload", {"model": "jev-1.13.0", "state": {"rubric_version": "rwr-1", "job_text": "synthetic"}, "questions": {"remote_work_readiness": {"type": "noul"}}})


class Connection:
    def __init__(self):
        self.commits = 0
        self.rollbacks = 0
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def commit(self): self.commits += 1
    def rollback(self): self.rollbacks += 1


class Connections:
    def __init__(self): self.items = []
    def __call__(self):
        conn = Connection()
        self.items.append(conn)
        return conn


def test_idle_does_not_call_rules(monkeypatch):
    monkeypatch.setattr(worker.store, "claim_due", lambda conn, **kwargs: None)
    monkeypatch.setattr(worker, "invoke_readiness", lambda *a, **k: pytest.fail("unexpected invocation"))
    conns = Connections()
    assert worker.run_once(conns, client=object(), api_key="", clock=lambda: NOW) == "idle"
    assert [c.commits for c in conns.items] == [1]


def test_rules_receives_exact_saved_payload_and_commits_claim_first(monkeypatch):
    job = Job()
    conns = Connections()
    monkeypatch.setattr(worker.store, "claim_due", lambda conn, **kwargs: job)
    class Answer:
        value = 0.987654321
        model = "jev-1.13.0"
        rubric_version = "rwr-1"
    calls = []
    def invoke(payload, catalog, handlers):
        assert conns.items[0].commits == 1
        assert payload is job.payload
        assert catalog["external_decisions"]["remote_work_readiness"]["handler"] == "jev"
        calls.append(payload)
        return Answer()
    monkeypatch.setattr(worker, "invoke_readiness", invoke)
    monkeypatch.setattr(worker.store, "complete", lambda conn, actual, answer, *, now: actual is job and answer.value == 0.987654321)
    assert worker.run_once(conns, client=object(), api_key="synthetic", clock=lambda: NOW) == "completed"
    assert len(calls) == 1 and conns.items[1].commits == 1


@pytest.mark.parametrize("retryable,expected", [(True, "retry_wait"), (False, "blocked")])
def test_failure_is_fenced_and_does_not_change_snapshot(monkeypatch, retryable, expected):
    from job_machine.remote_readiness.models import ReadinessError
    job = Job()
    conns = Connections()
    original = job.payload.copy()
    monkeypatch.setattr(worker.store, "claim_due", lambda conn, **kwargs: job)
    monkeypatch.setattr(worker, "invoke_readiness", lambda *a, **k: (_ for _ in ()).throw(ReadinessError("network_error", retryable)))
    seen = []
    monkeypatch.setattr(worker.store, "fail", lambda conn, actual, error, **kwargs: seen.append((actual, error.code)) or True)
    assert worker.run_once(conns, client=object(), api_key="synthetic", clock=lambda: NOW) == expected
    assert seen == [(job, "network_error")] and job.payload == original
    assert conns.items[1].commits == 1


def test_unexpected_handler_error_is_safely_blocked(monkeypatch):
    job = Job()
    conns = Connections()
    monkeypatch.setattr(worker.store, "claim_due", lambda conn, **kwargs: job)
    monkeypatch.setattr(
        worker,
        "invoke_readiness",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("provider secret detail")),
    )
    seen = []

    def fail(conn, actual, error, **kwargs):
        seen.append((actual, error.code, error.retryable, str(error)))
        return True

    monkeypatch.setattr(worker.store, "fail", fail)
    assert worker.run_once(conns, client=object(), api_key="synthetic", clock=lambda: NOW) == "blocked"
    assert seen == [(job, "handler_error", False, "handler_error")]
    assert conns.items[1].commits == 1


def test_late_response_cannot_complete_expired_lease(monkeypatch):
    job = Job()
    conns = Connections()
    monkeypatch.setattr(worker.store, "claim_due", lambda conn, **kwargs: job)
    monkeypatch.setattr(worker, "invoke_readiness", lambda *a, **k: object())
    monkeypatch.setattr(worker.store, "complete", lambda *a, **k: False)
    assert worker.run_once(conns, client=object(), api_key="synthetic", clock=lambda: NOW) == "lease_lost"
    assert conns.items[-1].rollbacks == 1 and not conns.items[-1].commits


def test_missing_or_malformed_worker_input_fails_closed(monkeypatch):
    from job_machine.remote_readiness.models import ReadinessError
    job = Job()
    conns = Connections()
    monkeypatch.setattr(worker.store, "claim_due", lambda conn, **kwargs: job)
    # The Jev handler validates the payload/key; a validation failure is no score.
    monkeypatch.setattr(worker, "invoke_readiness", lambda *a, **k: (_ for _ in ()).throw(ReadinessError("missing_api_key")))
    seen = []
    monkeypatch.setattr(worker.store, "fail", lambda conn, actual, error, **kwargs: seen.append(error.code) or True)
    assert worker.run_once(conns, client=object(), api_key="", clock=lambda: NOW) == "blocked"
    assert seen == ["missing_api_key"]


def test_lost_failure_lease_is_reported(monkeypatch):
    from job_machine.remote_readiness.models import ReadinessError
    monkeypatch.setattr(worker.store, "claim_due", lambda conn, **kwargs: Job())
    monkeypatch.setattr(worker, "invoke_readiness", lambda *a, **k: (_ for _ in ()).throw(ReadinessError("invalid_response")))
    monkeypatch.setattr(worker.store, "fail", lambda *a, **k: False)
    assert worker.run_once(Connections(), client=object(), api_key="key", clock=lambda: NOW) == "lease_lost"


def test_cli_uuid_validation_and_redacted_status(monkeypatch, capsys):
    from job_machine.remote_readiness import __main__ as cli
    with pytest.raises(SystemExit):
        cli.main(["resume-blocked", "--vacancy-id", "not-a-uuid"])
    monkeypatch.setattr(cli, "connect", lambda: _StatusConnection())
    assert cli.main(["status"]) == 0
    output = capsys.readouterr().out
    assert '"counts": {"blocked": 1}' in output
    assert '"intake_counts": {"pending": 2}' in output
    assert "payload" not in output and "secret" not in output


class _StatusConnection(Connection):
    def __init__(self):
        super().__init__()
        self.table = ""
    def execute(self, query, params=()):
        assert "remote_work_readiness_" in query
        self.table = "intake" if "_intake" in query else "job"
        return self
    def fetchone(self): return (False, None, None)
    def fetchall(self): return [("pending", 2)] if self.table == "intake" else [("blocked", 1)]


def test_cli_sanitizes_database_exception(monkeypatch, capsys):
    from job_machine.remote_readiness import __main__ as cli
    def bad_connect(): raise RuntimeError("secret DSN and raw payload")
    monkeypatch.setattr(cli, "connect", bad_connect)
    assert cli.main(["status"]) == 1
    output = capsys.readouterr().out
    assert output.strip() == '{"error": "operation_failed"}'
    assert "secret" not in output and "payload" not in output


def test_cli_unknown_vacancy_is_redacted(monkeypatch, capsys):
    from job_machine.remote_readiness import __main__ as cli
    class ResumeConnection(Connection):
        def execute(self, query, params):
            assert "remote_work_readiness_job" in query
            return self
        def fetchone(self): return None
    monkeypatch.setattr(cli, "connect", ResumeConnection)
    assert cli.main(["resume-blocked", "--vacancy-id", str(uuid4())]) == 0
    output = capsys.readouterr().out
    assert output.strip() == '{"resumed": false}'
    assert "payload" not in output and "secret" not in output


def test_cli_rearms_only_blocked_intake_and_emits_redacted_result(monkeypatch, capsys):
    from job_machine.remote_readiness import __main__ as cli
    vacancy_id = uuid4()
    calls = []
    monkeypatch.setattr(cli, "connect", lambda: _StatusConnection())
    monkeypatch.setattr(cli.intake_store, "rearm_blocked",
                        lambda conn, actual, *, now: calls.append(actual) or actual == vacancy_id)
    assert cli.main(["rearm-intake", "--vacancy-id", str(vacancy_id)]) == 0
    assert calls == [vacancy_id]
    assert capsys.readouterr().out.strip() == '{"resumed": true}'


def test_cli_prepare_once_reports_only_safe_outcome(monkeypatch, capsys):
    from job_machine.remote_readiness import __main__ as cli
    monkeypatch.setattr(cli.preparation, "run_once",
                        lambda *a, **k: "retry_wait")
    monkeypatch.setattr(cli.settings.ReadinessSettings, "from_env", lambda: type("Settings", (), {
        "enabled": True, "request_timeout_seconds": 30, "max_attempts": 5,
    })())
    monkeypatch.setattr(cli, "_control_enabled", lambda: True)
    assert cli.main(["prepare-once"]) == 0
    assert capsys.readouterr().out.strip() == '{"status": "retry_wait"}'


@pytest.mark.parametrize("enabled", [True, False])
def test_cli_enable_disable_is_idempotent_and_does_not_touch_queues(monkeypatch, capsys, enabled):
    from job_machine.remote_readiness import __main__ as cli
    calls = []
    monkeypatch.setattr(cli, "connect", _StatusConnection)
    monkeypatch.setattr(cli.control_store, "set_enabled",
                        lambda conn, value, *, actor: calls.append((value, actor)) or value)
    monkeypatch.setattr(cli.settings.ReadinessSettings, "from_env",
                        lambda: type("Settings", (), {"enabled": True})())
    action = "enable" if enabled else "disable"
    assert cli.main([action]) == 0
    first_output = capsys.readouterr().out.strip()
    assert cli.main([action]) == 0
    second_output = capsys.readouterr().out.strip()
    assert first_output == second_output == '{"enabled": ' + str(enabled).lower() + '}'
    assert calls == [(enabled, "rwr-cli"), (enabled, "rwr-cli")]


def test_cli_status_is_redacted_and_makes_no_provider_calls(monkeypatch, capsys):
    from job_machine.remote_readiness import __main__ as cli
    monkeypatch.setattr(cli, "connect", lambda: _ControlStatusConnection())
    monkeypatch.setattr(cli.settings.ReadinessSettings, "from_env", lambda: type("Settings", (), {
        "enabled": True, "intake_batch_limit": 4, "jev_batch_limit": 3,
        "concurrency": 1, "request_timeout_seconds": 30, "max_attempts": 5,
        "poll_interval_seconds": 30,
    })())
    monkeypatch.setattr(cli, "run_once", lambda *a, **k: pytest.fail("provider path called"))
    monkeypatch.setattr(cli.preparation, "run_once", lambda *a, **k: pytest.fail("ATS path called"))
    assert cli.main(["status"]) == 0
    output = capsys.readouterr().out
    assert '"enabled": true' in output
    assert '"intake_counts": {"pending": 2}' in output
    assert '"counts": {"blocked": 1}' in output
    assert all(secret not in output for secret in ("test-secret", "vacancy body", "provider response", "exception detail"))


class _ControlStatusConnection(_StatusConnection):
    def execute(self, query, params=()):
        self.query = query
        return self

    def fetchone(self):
        return (True, NOW, "rwr-cli")

    def fetchall(self):
        return [("pending", 2)] if "intake" in self.query else [("blocked", 1)]


def test_retry_after_is_safely_parsed_and_bounded():
    import httpx
    from job_machine.remote_readiness.jev import evaluate_payload
    from job_machine.remote_readiness.models import ReadinessError
    from job_machine.remote_readiness.jev import _retry_after_seconds
    assert _retry_after_seconds("30") == 30
    assert _retry_after_seconds("-3") is None
    assert _retry_after_seconds("1e999") is None
    assert _retry_after_seconds("not a date") is None
    assert _retry_after_seconds("999999") == 86400
    payload = Job().payload
    def transport(_request):
        return httpx.Response(429, headers={"Retry-After": "45"})
    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        with pytest.raises(ReadinessError) as caught:
            evaluate_payload(payload, client=client, api_key="synthetic")
    assert caught.value.retryable and caught.value.retry_after_seconds == 45
