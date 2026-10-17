"""One preparation and assessment per poll, with bounded safe diagnostics."""
from datetime import datetime, timezone
import json
from pathlib import Path
import signal
from threading import Event

from . import preparation, worker

HEALTH_PATH = Path('/tmp/job-fit-health')
OUTCOMES = frozenset(('idle', 'completed', 'prepared', 'retry_wait', 'blocked',
                      'lease_lost', 'quota_exhausted', 'operation_failed'))


def run(conn_factory, *, client, api_key, stop, clock,
        prepare_once=preparation.run_once, fit_once=worker.run_once,
        poll_seconds=5.0, wait=None, emit=None, health_path=HEALTH_PATH):
    if not 0 < poll_seconds <= 60:
        raise ValueError('invalid_poll_seconds')
    wait = wait or stop.wait
    emit = emit or (lambda value: print(json.dumps(value), flush=True))
    while not stop.is_set():
        counts = {}
        for name, operation, kwargs in (
            ('preparation', prepare_once, {}),
            ('fit', fit_once, {'client': client, 'api_key': api_key}),
        ):
            if stop.is_set():
                break
            try:
                outcome = operation(conn_factory, clock=clock, ats_family='greenhouse', **kwargs)
                counts[name] = outcome if outcome in OUTCOMES else 'operation_failed'
            except Exception:
                counts[name] = 'operation_failed'
        # A heartbeat proves a responsive loop; DB readiness is checked separately.
        health_path.write_text(str(clock().timestamp()), encoding='ascii')
        emit({**counts, 'counts': {name: {outcome: 1} for name, outcome in counts.items()}})
        wait(poll_seconds)


def healthy(path=HEALTH_PATH, *, now=None, max_age=90):
    try:
        age = (now or datetime.now(timezone.utc)).timestamp() - float(path.read_text(encoding='ascii'))
        return 0 <= age <= max_age
    except (OSError, ValueError):
        return False


def serve(conn_factory, *, client, api_key):
    stop = Event()
    previous = {}
    try:
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous[signum] = signal.signal(signum, lambda *_: stop.set())
        run(conn_factory, client=client, api_key=api_key, stop=stop,
            clock=lambda: datetime.now(timezone.utc))
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)
