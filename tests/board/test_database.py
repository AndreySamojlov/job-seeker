"""Synthetic records only; invoked exclusively through guarded check_schema.py."""
from datetime import date
import uuid

import pytest
from psycopg.rows import dict_row, tuple_row

from job_machine.board.models import BoardFilters, TablePage
from job_machine.board.repository import load_greenhouse_snapshot
from tests.conftest import apply_migrations

pytestmark = pytest.mark.db


def test_candidate_isolation_calendar_aggregation_and_server_paging(db_schema):
    conn, _ = db_schema
    apply_migrations(conn)
    conn.execute("INSERT INTO candidate(candidate_id,name) VALUES ('board-alpha','Alpha'),('board-beta','Beta')")
    for i in range(103):
        vacancy_id = uuid.UUID(int=i + 1)
        # 21:30 UTC belongs to the following Moscow calendar day.
        conn.execute("INSERT INTO vacancy(vacancy_id,source,ats_family,source_url,canonical_url,title,discovered_at) "
                     "VALUES (%s,'greenhouse','greenhouse',%s,%s,%s,'2026-10-13T21:30:00Z')",
                     (vacancy_id, f'https://boards-api.greenhouse.io/v1/boards/acme/jobs/{i}' if i < 102 else 'malformed',
                      f'https://example.test/{i}', f'Vacancy {i}'))
        if i < 102:
            conn.execute("INSERT INTO triage_result(candidate_id,vacancy_id,verdict,fit_score,fit_band,fit_score_version) "
                         "VALUES ('board-alpha',%s,'skip',0,'low','v1'),('board-beta',%s,'apply',99,'high','v2')", (vacancy_id, vacancy_id))
    conn.commit()
    # Only completed RWR values are visible to the read model. Zero is distinct
    # from NULL, and an in-progress result must behave like no result.
    readiness_values = [0.0, 0.3141592653589793, None, None]
    for i, (status, value) in enumerate((('completed', readiness_values[0]),
                                         ('completed', readiness_values[1]),
                                         ('pending', readiness_values[2]))):
        vacancy_id = uuid.UUID(int=i + 1)
        conn.execute("INSERT INTO remote_work_readiness_job(vacancy_id,status,payload,payload_hash,model,rubric_version,value,completed_at) "
                     "VALUES (%s,%s,'{}',%s,'jev-1.13.0','rwr-1',%s,CASE WHEN %s='completed' THEN now() ELSE NULL END)",
                     (vacancy_id, status, f'{i + 1:064x}', value, status))
    conn.commit()
    conn.row_factory = dict_row
    selection = BoardFilters('board-alpha', date(2026, 10, 13), date(2026, 10, 15))
    first = load_greenhouse_snapshot(conn, selection, TablePage(page=0))
    second = load_greenhouse_snapshot(conn, selection, TablePage(page=1))
    assert first.total_rows == second.total_rows == 103
    assert len(first.rows) == 100 and len(second.rows) == 3
    assert first.daily == [dict(day=date(2026, 10, 14), count=103)]
    assert {p['fit_score'] for p in first.points} == {0}
    assert first.unscored == 1 and first.unknown_board == 1
    readiness_by_id = {int(row['vacancy_id'].int): row['remote_work_readiness'] for row in first.rows}
    assert readiness_by_id[1] == 0.0
    assert readiness_by_id[2] == 0.3141592653589793
    assert readiness_by_id[3] is None  # pending is intentionally not exposed
    assert readiness_by_id[4] is None  # no readiness row
    assert not ({r['vacancy_id'] for r in first.rows} & {r['vacancy_id'] for r in second.rows})
    assert [r['vacancy_id'] for r in first.rows] == sorted(r['vacancy_id'] for r in first.rows)
    beta = load_greenhouse_snapshot(conn, BoardFilters('board-beta', selection.date_from, selection.date_to), TablePage())
    assert {p['fit_score'] for p in beta.points} == {99}
    filtered = load_greenhouse_snapshot(conn, BoardFilters('board-alpha', selection.date_from, selection.date_to, board='acme'), TablePage())
    assert filtered.total_rows == 102 and filtered.unknown_board == 0
    assert load_greenhouse_snapshot(conn, BoardFilters('board-alpha', selection.date_from, selection.date_to, board="';DROP"), TablePage()).total_rows == 0
    column_filtered = load_greenhouse_snapshot(conn, BoardFilters('board-alpha', selection.date_from, selection.date_to,
        column_filters='{"title":{"q":"Vacancy 10"},"fit_score":{"min":0,"max":0}}'), TablePage())
    assert column_filtered.total_rows == 3
    assert {row['title'] for row in column_filtered.rows} == {'Vacancy 10', 'Vacancy 100', 'Vacancy 101'}
    assert sum(row['count'] for row in column_filtered.boards) == 3
    assert sum(row['count'] for row in column_filtered.daily) == 3
    assert len(column_filtered.points) == 3
    assert load_greenhouse_snapshot(conn, BoardFilters('board-alpha', selection.date_from, selection.date_to,
        column_filters='{"title":{"q":"%_"}}'), TablePage()).total_rows == 0
    conn.row_factory = tuple_row
