from datetime import datetime, timezone
from threading import Event, Thread
import pytest


def test_ttl_boundary_and_failure_does_not_extend_it():
    from job_machine.ops.dashboard_state import SnapshotStore
    now = [0.0]
    store = SnapshotStore(monotonic=lambda: now[0])
    first = store.read('summary', lambda: [1])
    def broken():
        raise RuntimeError('password=synthetic')
    for age, state in [(200, 'stale'), (300, 'stale'), (300.01, 'unavailable')]:
        now[0] = age
        result = store.read('summary', broken)
        assert result.state == state
        assert 'synthetic' not in result.error
        if state == 'stale':
            assert result.fetched_at == first.fetched_at
    assert store.read('other', broken).state == 'unavailable'
    assert store.read('summary', lambda: []).data == []
    assert store.read('summary', broken).data == []


def test_older_completion_cannot_replace_newer_snapshot():
    from job_machine.ops.dashboard_state import SnapshotStore
    store = SnapshotStore()
    started, release = Event(), Event()
    def slow():
        started.set()
        assert release.wait(3)
        return ['old']
    thread = Thread(target=lambda: store.read('summary', slow))
    thread.start()
    try:
        assert started.wait(3)
        assert store.read('summary', lambda: ['new']).data == ['new']
    finally:
        release.set()
        thread.join(3)
    def broken(): raise RuntimeError('offline')
    assert store.read('summary', broken).data == ['new']


@pytest.mark.parametrize('states,expected', [
    (['live'] * 5, (200, 'live')),
    (['live', 'unavailable', 'live', 'live', 'live'], (200, 'partial')),
    (['stale', 'stale', 'unavailable', 'unavailable', 'live'], (200, 'stale')),
    (['unavailable'] * 4 + ['live'], (503, 'unavailable')),
    (['live'] * 4 + ['unavailable'], (200, 'partial')),
])
def test_outcome_distinguishes_partial_and_infrastructure_only(states, expected):
    from job_machine.ops.dashboard_state import BlockResult, page_outcome
    names = ['summary', 'blockers', 'ready', 'observations', 'status']
    blocks = {k: BlockResult(s, [], datetime.now(timezone.utc), None) for k, s in zip(names, states)}
    assert page_outcome(blocks) == expected
