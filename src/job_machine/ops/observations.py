"""Validate existing event metadata; events are not worker heartbeats."""
from datetime import datetime
from job_machine.ops.remote_data import USEFUL_EVENTS


def normalize_observations(rows: list[dict]) -> dict[str, dict | None]:
    result = {'latest_event': None, 'latest_result': None}
    if not isinstance(rows, list):
        raise ValueError('Invalid observations response')
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('Invalid observation row')
        kind = row.get('kind')
        event_type = row.get('event_type')
        if (not isinstance(kind, str) or kind not in result or result[kind] is not None
                or not isinstance(event_type, str) or not event_type or not row.get('event_id')):
            raise ValueError('Invalid observation identity')
        if kind == 'latest_result' and event_type not in USEFUL_EVENTS:
            raise ValueError('Unrecognized useful result')
        timestamp = row.get('created_at')
        if isinstance(timestamp, str):
            try:
                timestamp = datetime.fromisoformat(timestamp)
            except ValueError:
                raise ValueError('Invalid observation timestamp') from None
        if not isinstance(timestamp, datetime) or timestamp.utcoffset() is None:
            raise ValueError('Observation timestamp must include timezone')
        result[kind] = dict(event_id=str(row['event_id']), event_type=event_type, created_at=timestamp)
    return result
