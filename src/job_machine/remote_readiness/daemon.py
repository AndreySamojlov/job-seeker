"""Isolated, bounded polling runtime for remote-work readiness."""
from __future__ import annotations

import httpx
import json
import os
import signal
from datetime import datetime, timezone
from threading import Event
from pathlib import Path
from typing import Callable

from job_machine.db.connection import connect

from . import control_store, preparation, worker
from .settings import ReadinessSettings

_SAFE_OUTCOMES = {
    "prepared", "existing", "retry_wait", "blocked", "gone",
    "completed", "lease_lost",
}
DEFAULT_POLL_INTERVAL_SECONDS = 30


def _settings():
    return ReadinessSettings.from_env()


def _provider_key() -> str:
    """Load the provider key only in an enabled cycle; never expose the source."""
    secret_file = os.environ.get("TYPESAFE_API_KEY_FILE")
    if isinstance(secret_file, str) and secret_file.strip():
        try:
            value = Path(secret_file).read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError):
            raise ValueError("missing_rwr_api_key") from None
        if value:
            return value
        raise ValueError("missing_rwr_api_key")
    return os.environ.get("TYPESAFE_API_KEY", "")


def _persistent_enabled(conn_factory) -> bool:
    with conn_factory() as conn:
        return control_store.is_enabled(conn)


def _emit_heartbeat(emit, state, intake_counts, jev_counts, *, at):
    emit({"event": "heartbeat", "at": at, "state": state,
          "intake": dict(sorted(intake_counts.items())),
          "jev": dict(sorted(jev_counts.items()))})


def _record(counts, outcome):
    if outcome in _SAFE_OUTCOMES:
        counts[outcome] = counts.get(outcome, 0) + 1


def _still_enabled(configured, conn_factory):
    return configured.enabled and _persistent_enabled(conn_factory)


def run_daemon(*, conn_factory=connect, stop_event: Event, wait: Callable[[float], bool] | None = None,
               emit: Callable[[dict], None] = print, settings_factory=None,
               jev_client_factory=None, api_key: str | None = None,
               clock: Callable[[], datetime] | None = None) -> None:
    """Poll only the RWR queues; stop between items when SIGTERM is received.

    Work per poll is capped by the configured intake and Jev batch limits. The
    settings and persistent kill switch are checked before each provider item.
    ``wait`` is injectable so interval and shutdown behavior can be tested
    without wall-clock sleeps.
    """
    wait = wait or stop_event.wait
    settings_factory = settings_factory or _settings
    clock = clock or (lambda: datetime.now(timezone.utc))
    jev_client_factory = jev_client_factory or (
        lambda configured: httpx.Client(timeout=configured.request_timeout_seconds)
    )
    while not stop_event.is_set():
        intake_counts: dict[str, int] = {}
        jev_counts: dict[str, int] = {}
        state = "active"
        configured = None
        try:
            configured = settings_factory()
            if not configured.enabled or not _persistent_enabled(conn_factory):
                state = "disabled"
            else:
                provider_key = _provider_key() if api_key is None else api_key
                if not isinstance(provider_key, str) or not provider_key.strip():
                    raise ValueError("missing_rwr_api_key")
                for _ in range(configured.intake_batch_limit):
                    if stop_event.is_set() or not _still_enabled(configured, conn_factory):
                        state = "disabled"
                        break
                    outcome = preparation.run_once(
                        conn_factory, max_attempts=configured.max_attempts)
                    if outcome == "idle":
                        break
                    _record(intake_counts, outcome)

                if state != "disabled" and not stop_event.is_set():
                    if _still_enabled(configured, conn_factory):
                        client = jev_client_factory(configured)
                        try:
                            for _ in range(configured.jev_batch_limit):
                                if stop_event.is_set() or not _still_enabled(configured, conn_factory):
                                    state = "disabled"
                                    break
                                outcome = worker.run_once(
                                    conn_factory, client=client, api_key=provider_key,
                                    max_attempts=configured.max_attempts,
                                    timeout_seconds=configured.request_timeout_seconds,
                                )
                                if outcome == "idle":
                                    break
                                _record(jev_counts, outcome)
                        finally:
                            close = getattr(client, "close", None)
                            if callable(close):
                                close()
                    else:
                        state = "disabled"
        except Exception:
            # Runtime errors are intentionally collapsed: never emit DSNs,
            # vacancy content, provider responses, credentials, or exception text.
            state = "operation_failed"

        _emit_heartbeat(emit, state, intake_counts, jev_counts, at=clock().isoformat())
        interval = configured.poll_interval_seconds if configured is not None else DEFAULT_POLL_INTERVAL_SECONDS
        if stop_event.is_set() or wait(interval):
            break


def main() -> int:
    stop_event = Event()

    def request_stop(_signum, _frame):
        stop_event.set()

    previous = {}
    for sig in (signal.SIGTERM, signal.SIGINT):
        previous[sig] = signal.signal(sig, request_stop)
    try:
        def emit(event):
            print(json.dumps(event, ensure_ascii=True), flush=True)
        run_daemon(stop_event=stop_event, emit=emit)
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
