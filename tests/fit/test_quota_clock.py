from datetime import datetime, timezone
from uuid import uuid4

from job_machine.fit.quota import reserve_request


def test_reservation_clock_is_sampled_after_quota_lock():
    class Result:
        def __init__(self, row): self.row = row
        def fetchone(self): return self.row

    class Connection:
        locked = False
        inserted = None

        def execute(self, statement, params=None):
            if statement == "show transaction_isolation":
                return Result(("read committed",))
            if "pg_advisory_xact_lock" in statement:
                self.locked = True
                return Result((None,))
            if statement.startswith("select count(*)"):
                return Result((0,))
            if statement.startswith("insert into event"):
                self.inserted = params
                return Result((None,))
            raise AssertionError(statement)

    conn = Connection()
    reserved_at = datetime(2030, 1, 2, 0, 0, 1, tzinfo=timezone.utc)

    def clock_after_lock():
        assert conn.locked
        return reserved_at

    assert reserve_request(conn, entity_type="vacancy", entity_id=uuid4(), now=clock_after_lock)
    assert conn.inserted[3] == reserved_at
