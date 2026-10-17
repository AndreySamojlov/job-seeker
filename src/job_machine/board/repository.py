"""Single read-only PostgreSQL snapshot; no schema or worker mutations."""
from datetime import datetime, time, timedelta, timezone

from job_machine.board.models import BoardFilters, GreenhouseSnapshot, MOSCOW, TablePage, ReadStamp
from job_machine.board.read_budget import MAX_ROWS, ReadBudget, SnapshotTooLarge
from job_machine.board.column_filters import filter_sql

# Only the persisted per-job API URL proves board identity. Company is not a key.
BASE = r"""
WITH source AS (
 SELECT v.*, substring(source_url from
 '^https://boards-api[.]greenhouse[.]io/v1/boards/([A-Za-z0-9_-]+)/jobs/[0-9]+$') AS board_token
 FROM vacancy v WHERE v.ats_family = 'greenhouse' AND v.source = 'greenhouse'
), selected AS (
 SELECT v.vacancy_id, v.title, v.canonical_url AS url, v.company, v.location,
        v.work_mode, v.discovered_at, v.board_token, t.fit_score,
        'Неизвестно'::text AS availability, NULL::timestamptz AS availability_checked_at
 FROM source v LEFT JOIN (
   SELECT candidate_id, vacancy_id, score AS fit_score FROM fit_job WHERE status = 'completed'
 ) t
   ON t.vacancy_id = v.vacancy_id AND t.candidate_id = %(candidate)s
 WHERE v.discovered_at >= %(start)s AND v.discovered_at < %(end)s
   AND (%(board)s::text IS NULL OR v.board_token = %(board)s)
   /* column_filters */
)
"""


def load_greenhouse_snapshot(conn, filters: BoardFilters, table_page: TablePage, *, budget=None) -> GreenhouseSnapshot:
    budget = budget or ReadBudget()
    with conn.transaction():
        budget.source_remaining_ms()
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        stamp = ReadStamp()
        def execute(sql, params=None):
            timeout = budget.statement_timeout_ms()
            conn.execute(f"SET LOCAL statement_timeout = '{timeout}ms'")
            return conn.execute(sql, params)
        candidates = execute('SELECT candidate_id, name FROM candidate WHERE active ORDER BY candidate_id').fetchall()
        candidate_id = filters.candidate_id
        if candidate_id is None and len(candidates) == 1:
            candidate_id = candidates[0]['candidate_id']
        if candidate_id is not None and candidate_id not in {c['candidate_id'] for c in candidates}:
            raise ValueError('Candidate unavailable')
        result = GreenhouseSnapshot(candidate_id=candidate_id, candidates=candidates, stamp=stamp)
        if candidate_id is None:
            return result
        params = dict(candidate=candidate_id, board=filters.board,
                      start=datetime.combine(filters.date_from, time.min, MOSCOW),
                      end=datetime.combine(filters.date_to + timedelta(days=1), time.min, MOSCOW))
        column_where, column_params = filter_sql(filters.column_filters)
        params.update(column_params)
        def query(suffix):
            return execute(BASE.replace('/* column_filters */', column_where) + suffix, params)
        result.board_options = [r['token'] for r in query(
            'SELECT DISTINCT board_token AS token FROM source WHERE board_token IS NOT NULL ORDER BY token').fetchall()]
        counts = query('SELECT count(*) AS total_rows, count(*) FILTER (WHERE board_token IS NULL) AS unknown_board, '
                       'count(*) FILTER (WHERE fit_score IS NULL) AS unscored FROM selected').fetchone()
        result.total_rows, result.unknown_board, result.unscored = (counts[k] for k in ('total_rows', 'unknown_board', 'unscored'))
        if result.total_rows > MAX_ROWS:
            raise SnapshotTooLarge()
        result.daily = query("SELECT (discovered_at AT TIME ZONE 'Europe/Moscow')::date AS day, count(*) AS count "
                             'FROM selected GROUP BY day ORDER BY day').fetchall()
        result.bands = query("SELECT fit_score::text AS label, count(*) AS count FROM selected "
                             'WHERE fit_score IS NOT NULL GROUP BY fit_score ORDER BY fit_score').fetchall()
        result.boards = query("SELECT board_token AS token, min(nullif(btrim(company), '')) AS company, "
                              'count(*) AS count FROM selected GROUP BY board_token ORDER BY count DESC, token').fetchall()
        result.points = query('SELECT discovered_at, fit_score FROM selected WHERE fit_score IS NOT NULL ORDER BY discovered_at, vacancy_id').fetchall()
        # Browser sorts and pages the complete snapshot; transport identity is stable.
        result.rows = query('SELECT * FROM selected ORDER BY vacancy_id').fetchall()
        result.fetched_at = datetime.now(timezone.utc)
        budget.source_remaining_ms()
        return result
