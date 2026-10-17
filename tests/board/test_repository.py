from contextlib import contextmanager
from datetime import date

import pytest

from job_machine.board.models import BoardFilters, TablePage
from job_machine.board.repository import load_greenhouse_snapshot


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
    result = load_greenhouse_snapshot(conn, selection, TablePage(sort_key='fit_score'))
    assert result.total_rows == 0
    sql_text = '\n'.join(s for s, p in conn.calls)
    assert 'REPEATABLE READ READ ONLY' in sql_text
    assert 'statement_timeout' in sql_text
    assert "x';DROP" not in sql_text
    assert 'LIMIT 100 OFFSET' not in sql_text
    assert 'SELECT * FROM selected ORDER BY vacancy_id' in sql_text


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


def test_jev_sql_is_candidate_scoped_completed_only_and_filterable():
    conn = Connection()
    load_greenhouse_snapshot(conn, BoardFilters('alpha', date(2026, 10, 15), date(2026, 10, 15),
        column_filters='{"fit_score":{"min":0,"max":0}}'), TablePage(page=2, sort_key='title'))
    selected_queries = [(sql, params) for sql, params in conn.calls if 'WITH source' in sql]
    for sql, params in selected_queries:
        assert 'triage_result' not in sql
        assert 'FROM fit_job' in sql
        assert "status = 'completed'" in sql
        assert 'score AS fit_score' in sql
        assert 't.vacancy_id = v.vacancy_id AND t.candidate_id = %(candidate)s' in sql
        assert params['candidate'] == 'alpha'
        assert 't.fit_score >= %(column_fit_min)s' in sql
        assert params['column_fit_min'] == params['column_fit_max'] == 0
    assert any('fit_score::text AS label' in sql for sql, _ in selected_queries)


@pytest.mark.parametrize('count', [103, 100000, 100001])
def test_full_snapshot_row_cap_rejects_before_fetching_partial_rows(count):
    from job_machine.board import read_budget
    class Sized(Connection):
        def execute(self, sql, params=None):
            result = super().execute(sql, params)
            if 'AS total_rows' in sql:
                return Cursor([dict(total_rows=count, unknown_board=0, unscored=count)])
            if 'SELECT * FROM selected' in sql:
                return Cursor([{'vacancy_id': i, 'fit_score': None} for i in range(count)])
            return result
    conn = Sized()
    if count > 100000:
        with pytest.raises(read_budget.SnapshotTooLarge, match='snapshot_too_large'):
            load_greenhouse_snapshot(conn, BoardFilters('alpha', date(2026, 10, 15), date(2026, 10, 15)), TablePage(page=17))
        assert not any('SELECT * FROM selected' in sql for sql, _ in conn.calls)
    else:
        result = load_greenhouse_snapshot(conn, BoardFilters('alpha', date(2026, 10, 15), date(2026, 10, 15)), TablePage(page=17))
        assert len(result.rows) == result.total_rows == count


@pytest.mark.db
def test_recovery_jev_completed_scores_candidate_isolation_and_full_filtered_aggregates(db_schema):
    # Synthetic rows prove SQL behavior: no candidate leakage, missing/unfinished
    # jobs remain unscored, and SQL filters see Jev rather than legacy triage.
    import uuid
    from psycopg.rows import dict_row, tuple_row
    from tests.conftest import apply_migrations
    conn, _ = db_schema
    apply_migrations(conn)
    conn.execute("INSERT INTO candidate(candidate_id,name) VALUES ('alpha','Alpha'),('beta','Beta')")
    statuses = ['completed', 'pending', 'processing', 'retry_wait', 'blocked', None]
    for i in range(103):
        vacancy = uuid.UUID(int=i + 1)
        conn.execute("INSERT INTO vacancy(vacancy_id,source,ats_family,source_url,canonical_url,title,discovered_at) "
                     "VALUES (%s,'greenhouse','greenhouse',%s,%s,%s,'2026-10-14T12:00:00Z')",
                     (vacancy, f'https://boards-api.greenhouse.io/v1/boards/acme/jobs/{i}',
                      f'https://example.test/{i}', f'Vacancy {i}'))
        conn.execute("INSERT INTO triage_result(candidate_id,vacancy_id,verdict,fit_score,fit_band,fit_score_version) "
                     "VALUES ('alpha',%s,'skip',87,'high','legacy')", (vacancy,))
        status = statuses[i] if i < 6 else 'completed'
        if status:
            conn.execute("INSERT INTO fit_job(candidate_id,vacancy_id,status,payload,payload_hash,model,rubric_version,score,"
                         "completed_at,lease_token,lease_until,next_attempt_at) "
                         "VALUES ('alpha',%s,%s,'{}',%s,'synthetic','test',%s,%s,%s,%s,%s)",
                         (vacancy, status, 'a' * 64, 0 if status == 'completed' else None,
                          '2026-10-15T00:00:00Z' if status == 'completed' else None,
                          uuid.UUID(int=999) if status == 'processing' else None,
                          '2026-10-16T00:00:00Z' if status == 'processing' else None,
                          '2026-10-16T00:00:00Z' if status == 'retry_wait' else None))
        conn.execute("INSERT INTO fit_job(candidate_id,vacancy_id,status,payload,payload_hash,model,rubric_version,score,completed_at) "
                     "VALUES ('beta',%s,'completed','{}',%s,'synthetic','test',99,'2026-10-15T00:00:00Z')", (vacancy, 'b' * 64))
    conn.commit()
    conn.row_factory = dict_row
    filters = BoardFilters('alpha', date(2026, 10, 14), date(2026, 10, 15))
    result = load_greenhouse_snapshot(conn, filters, TablePage(page=12, sort_key='title', sort_direction='desc'))
    assert result.total_rows == len(result.rows) == 103
    assert result.unscored == 5
    assert [r['fit_score'] for r in result.rows[:6]] == [0, None, None, None, None, None]
    assert [r['vacancy_id'] for r in result.rows] == [uuid.UUID(int=i + 1) for i in range(103)]
    assert result.bands == [{'label': '0', 'count': 98}]
    assert len(result.points) == 98
    assert set(result.rows[0]) == {'vacancy_id', 'title', 'url', 'company', 'location', 'work_mode',
                                   'discovered_at', 'board_token', 'fit_score', 'availability', 'availability_checked_at'}
    beta = load_greenhouse_snapshot(conn, BoardFilters('beta', filters.date_from, filters.date_to), TablePage())
    assert beta.total_rows == 103 and beta.unscored == 0
    assert {r['fit_score'] for r in beta.rows} == {99}
    filtered = load_greenhouse_snapshot(conn, BoardFilters('alpha', filters.date_from, filters.date_to,
        column_filters='{"title":{"q":"Vacancy 10"},"fit_score":{"min":0,"max":0}}'), TablePage())
    assert {r['title'] for r in filtered.rows} == {'Vacancy 10', 'Vacancy 100', 'Vacancy 101', 'Vacancy 102'}
    assert filtered.total_rows == 4 and filtered.unscored == 0
    assert filtered.daily == [{'day': date(2026, 10, 14), 'count': 4}]
    assert filtered.bands == [{'label': '0', 'count': 4}]
    assert sum(r['count'] for r in filtered.boards) == len(filtered.points) == 4
    conn.row_factory = tuple_row
