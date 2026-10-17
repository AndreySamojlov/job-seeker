"""Conservative durable UTC-day admissions. Callers commit before network I/O."""
from datetime import datetime, timedelta, timezone
from typing import Callable
from uuid import UUID

EVENT_TYPE = 'fit.jev_request_reserved'
LOCK_ID = 0x4A4556464954


def next_midnight(now: datetime) -> datetime:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('timezone_required')
    return now.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)


def reserve_request(conn, *, entity_type: str, entity_id: UUID,
                    now: datetime | Callable[[], datetime], daily_limit: int = 1000) -> bool:
    if type(daily_limit) is not int or not 1 <= daily_limit <= 1000:
        raise ValueError('invalid_daily_limit')
    if conn.execute("show transaction_isolation").fetchone()[0] != 'read committed':
        raise ValueError('read_committed_required')
    # Separate statements: READ COMMITTED takes a new snapshot after lock wait.
    conn.execute('select pg_advisory_xact_lock(%s)', (LOCK_ID,))
    # Sample the clock only after serialization. A claim or DB reconnect may
    # have crossed UTC midnight while waiting for the global quota lock.
    reserved_at = now() if callable(now) else now
    end = next_midnight(reserved_at)
    count = conn.execute('select count(*) from event where event_type=%s and created_at >= %s and created_at < %s',
                         (EVENT_TYPE, end - timedelta(days=1), end)).fetchone()[0]
    if count >= daily_limit:
        return False
    conn.execute('insert into event(entity_type,entity_id,event_type,created_at) values (%s,%s,%s,%s)',
                 (entity_type, entity_id, EVENT_TYPE, reserved_at))
    return True
