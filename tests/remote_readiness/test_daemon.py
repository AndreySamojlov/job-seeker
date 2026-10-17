from threading import Event
from types import SimpleNamespace
from datetime import datetime, timezone

from job_machine.remote_readiness import daemon


class Connection:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_disabled_daemon_has_no_provider_calls_and_reports_redacted_heartbeat(monkeypatch):
    settings = SimpleNamespace(enabled=False, poll_interval_seconds=7,
                               intake_batch_limit=2, jev_batch_limit=2,
                               request_timeout_seconds=30, max_attempts=3)
    monkeypatch.setattr(daemon, "_settings", lambda: settings)
    monkeypatch.setattr(daemon.control_store, "is_enabled", lambda _conn: True)
    monkeypatch.setattr(daemon.preparation, "run_once", lambda *a, **k: (_ for _ in ()).throw(AssertionError("ATS called")))
    monkeypatch.setattr(daemon.worker, "run_once", lambda *a, **k: (_ for _ in ()).throw(AssertionError("Jev called")))
    event = Event()
    heartbeats = []
    waits = []

    def wait(seconds):
        waits.append(seconds)
        event.set()
        return event.is_set()

    daemon.run_daemon(conn_factory=Connection, stop_event=event, wait=wait,
                      emit=heartbeats.append, jev_client_factory=lambda *_: None,
                      clock=lambda: datetime(2030, 1, 1, tzinfo=timezone.utc))

    assert waits == [7]
    assert heartbeats == [{"event": "heartbeat", "at": "2030-01-01T00:00:00+00:00",
                           "state": "disabled", "intake": {}, "jev": {}}]


def test_enabled_daemon_processes_bounded_fake_provider_work_and_stops(monkeypatch):
    settings = SimpleNamespace(enabled=True, poll_interval_seconds=5,
                               intake_batch_limit=2, jev_batch_limit=3,
                               request_timeout_seconds=41, max_attempts=4)
    monkeypatch.setattr(daemon, "_settings", lambda: settings)
    monkeypatch.setattr(daemon.control_store, "is_enabled", lambda _conn: True)
    intake_calls, jev_calls, wait_calls, heartbeats = [], [], [], []
    intake_results = iter(["prepared", "idle"])
    jev_results = iter(["completed", "retry_wait", "idle"])
    monkeypatch.setattr(daemon.preparation, "run_once", lambda *a, **kw:
                        intake_calls.append(kw.copy()) or next(intake_results))
    monkeypatch.setattr(daemon.worker, "run_once", lambda *a, **kw:
                        jev_calls.append(kw.copy()) or next(jev_results))
    stop = Event()

    def wait(seconds):
        wait_calls.append(seconds)
        stop.set()
        return True

    client = object()
    daemon.run_daemon(conn_factory=Connection, stop_event=stop, wait=wait,
                      emit=heartbeats.append, jev_client_factory=lambda actual: client,
                      api_key="synthetic", clock=lambda: datetime(2030, 1, 1, tzinfo=timezone.utc))

    assert len(intake_calls) == 2
    assert all(call["max_attempts"] == 4 for call in intake_calls)
    assert len(jev_calls) == 3
    assert all(call["max_attempts"] == 4 and call["timeout_seconds"] == 41 for call in jev_calls)
    assert all(call["client"] is client and call["api_key"] == "synthetic" for call in jev_calls)
    assert wait_calls == [5]
    assert heartbeats == [{"event": "heartbeat", "at": "2030-01-01T00:00:00+00:00",
                           "state": "active", "intake": {"prepared": 1},
                           "jev": {"completed": 1, "retry_wait": 1}}]


def test_persistent_disabled_control_suppresses_provider_calls(monkeypatch):
    settings = SimpleNamespace(enabled=True, poll_interval_seconds=11,
                               intake_batch_limit=1, jev_batch_limit=1,
                               request_timeout_seconds=30, max_attempts=4)
    monkeypatch.setattr(daemon, "_settings", lambda: settings)
    monkeypatch.setattr(daemon.control_store, "is_enabled", lambda _conn: False)
    monkeypatch.setattr(daemon.preparation, "run_once", lambda *a, **k: (_ for _ in ()).throw(AssertionError("ATS called")))
    monkeypatch.setattr(daemon.worker, "run_once", lambda *a, **k: (_ for _ in ()).throw(AssertionError("Jev called")))
    stop = Event()
    heartbeats = []

    def wait(_seconds):
        stop.set()
        return True

    daemon.run_daemon(conn_factory=Connection, stop_event=stop, wait=wait,
                      emit=heartbeats.append, jev_client_factory=lambda *_: None)

    assert heartbeats[0]["state"] == "disabled"


def test_cli_sigterm_handler_requests_graceful_stop(monkeypatch):
    handlers = {}
    event_seen = []

    def set_handler(sig, handler):
        previous = handlers.get(sig, "previous")
        handlers[sig] = handler
        return previous

    def run(**kwargs):
        event_seen.append(kwargs["stop_event"])
        handlers[daemon.signal.SIGTERM](daemon.signal.SIGTERM, None)
        assert kwargs["stop_event"].is_set()

    monkeypatch.setattr(daemon.signal, "signal", set_handler)
    monkeypatch.setattr(daemon, "run_daemon", run)
    assert daemon.main() == 0
    assert len(event_seen) == 1


def test_provider_secret_file_is_loaded_without_exposing_path_or_value(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY_FILE", "private-key-path")
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.setattr(daemon.Path, "read_text", lambda self, encoding: "synthetic-secret\n")
    assert daemon._provider_key() == "synthetic-secret"
