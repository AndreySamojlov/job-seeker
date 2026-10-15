from datetime import datetime, timezone
import sqlite3
import pytest
from job_machine.ops.remote_data import query


def test_latest_result_is_selected_before_limiting_events():
    sql, params = query({'view': 'observations'})
    # Execute the emitted relational query on synthetic data; PostgreSQL is
    # separately verified read-only. No mock chooses the expected result.
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    conn.execute('create table event(event_id text,event_type text,created_at text)')
    conn.execute("insert into event values ('a','vacancy.verified','2026-10-01T00:00:00+00:00')")
    conn.executemany('insert into event values (?,?,?)', [
        (str(i), 'application.failed', f'2026-10-02T00:{i:02}:00+00:00') for i in range(40)])
    conn.execute("insert into event values ('z','vacancy.discovered',NULL)")
    rows = [dict(r) for r in conn.execute(sql.replace('%s', '?'), params)]
    assert {r['kind']: r['event_type'] for r in rows} == {
        'latest_event': 'application.failed', 'latest_result': 'vacancy.verified'}
    assert next(r for r in rows if r['kind'] == 'latest_result')['event_id'] == 'a'
    assert set(rows[0]) == {'kind', 'event_id', 'event_type', 'created_at'}


def test_normalize_empty_and_unknown_event():
    from job_machine.ops.observations import normalize_observations
    assert normalize_observations([]) == {'latest_event': None, 'latest_result': None}
    row = dict(kind='latest_event', event_id='a', event_type='future.event',
               created_at='2026-10-15T00:00:00+00:00')
    normalized = normalize_observations([row])
    assert normalized['latest_event']['event_type'] == 'future.event'
    assert normalized['latest_event']['created_at'] == datetime(2026, 10, 15, tzinfo=timezone.utc)


@pytest.mark.parametrize('patch', [
    {'created_at': '2026-10-15T00:00:00'}, {'created_at': 'broken'},
    {'created_at': None}, {'kind': 'arbitrary'}, {'event_type': None},
    {'kind': 'latest_result', 'event_type': 'application.failed'},
])
def test_invalid_observation_is_not_activity(patch):
    from job_machine.ops.observations import normalize_observations
    row = dict(kind='latest_event', event_id='a', event_type='vacancy.verified',
               created_at='2026-10-15T00:00:00+00:00')
    row.update(patch)
    with pytest.raises(ValueError):
        normalize_observations([row])


def test_duplicate_kind_is_rejected():
    from job_machine.ops.observations import normalize_observations
    row = dict(kind='latest_event', event_id='a', event_type='vacancy.verified',
               created_at=datetime.now(timezone.utc))
    with pytest.raises(ValueError):
        normalize_observations([row, row])
