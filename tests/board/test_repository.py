from contextlib import contextmanager
from datetime import date

import pytest

from job_machine.board.models import BoardFilters, TablePage, SORT_KEYS
from job_machine.board.repository import load_greenhouse_snapshot
from job_machine.board.column_filters import parse_column_filters, TEXT_FIELDS


class Cursor:
    def __init__(self, rows): self.rows = rows
    def fetchall(self): return self.rows
    def fetchone(self): return self.rows[0]


class Connection:
    def __init__(self): self.calls = []; self.in_transaction = False
    @contextmanager
    def transaction(self):
        self.in_transaction = True
        try: yield
        finally: self.in_transaction = False
    def execute(self, sql, params=None):
        assert self.in_transaction
        self.calls.append((sql, params))
        if 'FROM candidate' in sql: return Cursor([{'candidate_id': 'alpha', 'name': 'Alpha'}, {'candidate_id': 'beta', 'name': 'Beta'}])
        if 'AS total_rows' in sql: return Cursor([dict(total_rows=0, unknown_board=0, unscored=0)])
        return Cursor([])


def test_transaction_and_parameterization():
    conn = Connection()
    selection = BoardFilters('alpha', date(2026, 10, 13), date(2026, 10, 15), board="x';DROP TABLE vacancy;--")
    result = load_greenhouse_snapshot(conn, selection, TablePage(page=2, sort_key='fit_score'))
    assert result.total_rows == 0
    sql_text = '\n'.join(s for s, p in conn.calls)
    assert 'REPEATABLE READ READ ONLY' in sql_text
    assert 'statement_timeout' in sql_text
    assert "x';DROP" not in sql_text
    assert 'LIMIT 100 OFFSET' not in sql_text
    assert 'SELECT * FROM selected ORDER BY vacancy_id' in sql_text
    assert 'LEFT JOIN remote_work_readiness_job r' in sql_text
    assert "r.status = 'completed'" in sql_text
    assert 'r.value AS remote_work_readiness' in sql_text
    assert 'remote_work_readiness' not in SORT_KEYS
    assert 'remote_work_readiness' not in TEXT_FIELDS
    with pytest.raises(ValueError, match='Invalid column filters'):
        parse_column_filters('{"remote_work_readiness":{"min":0}}')


def test_multiple_candidates_never_silently_choose_one():
    conn = Connection()
    result = load_greenhouse_snapshot(conn, BoardFilters(None, date(2026, 10, 15), date(2026, 10, 15)), TablePage())
    assert result.candidate_id is None
    assert not any('LEFT JOIN' in sql for sql, params in conn.calls)


def test_unknown_candidate_is_rejected_before_analytics():
    with pytest.raises(ValueError):
        load_greenhouse_snapshot(Connection(), BoardFilters('missing', date(2026, 10, 15), date(2026, 10, 15)), TablePage())


def test_each_query_uses_remaining_source_budget():
    from job_machine.board.read_budget import ReadBudget, ReadDeadline
    now = [0]
    class Slow(Connection):
        def execute(self, sql, params=None):
            result = super().execute(sql, params)
            if 'FROM candidate' in sql:
                now[0] = 14900
            if 'SELECT DISTINCT' in sql:
                now[0] = 15000
            return result
    conn = Slow()
    with pytest.raises(ReadDeadline):
        load_greenhouse_snapshot(conn, BoardFilters('alpha', date(2026, 10, 15), date(2026, 10, 15)), TablePage(), budget=ReadBudget(now_ms=lambda: now[0]))
    assert any("'100ms'" in sql for sql, _ in conn.calls)
    assert not any('AS total_rows' in sql for sql, _ in conn.calls)
