from datetime import date, datetime, timezone

import pytest

from job_machine.board.models import BoardFilters, GreenhouseSnapshot, TablePage
from job_machine.board.greenhouse import build_greenhouse_report


def snapshot(**changes):
    values = dict(candidate_id='alpha', candidates=[{'candidate_id': 'alpha', 'name': 'Alpha'}],
                  board_options=['acme'], total_rows=3, unknown_board=1, unscored=1,
                  daily=[{'day': date(2026, 10, 13), 'count': 1}, {'day': date(2026, 10, 15), 'count': 2}],
                  bands=[{'label': '0', 'count': 1}, {'label': '90', 'count': 1}],
                  boards=[{'token': 'acme', 'count': 2}, {'token': None, 'count': 1}],
                  points=[{'discovered_at': datetime(2026, 10, 13, tzinfo=timezone.utc), 'fit_score': 0},
                          {'discovered_at': datetime(2026, 10, 15, tzinfo=timezone.utc), 'fit_score': 90}],
                  rows=[{'vacancy_id': 'synthetic', 'title': '<img src=x>', 'url': 'javascript:alert(1)', 'fit_score': 0, 'remote_work_readiness': None, 'board_token': None}],
                  fetched_at=datetime(2026, 10, 15, tzinfo=timezone.utc))
    values.update(changes)
    return GreenhouseSnapshot(**values)


def test_report_preserves_zero_unknowns_and_calendar_days():
    report = build_greenhouse_report(snapshot(), BoardFilters('alpha', date(2026, 10, 13), date(2026, 10, 15)))
    assert [k['value'] for k in report['kpis']] == ['1', 'Нет данных', '1', 'Нет данных']
    assert report['charts']['chart_series'][0]['series'][0]['y'] == [1, 0, 2]
    assert report['charts']['chart_series'][1]['x'] == ['0', '90']
    assert report['charts']['chart_series'][3]['series'][0]['data'][0]['y'] == 0
    assert report['charts']['specs'][3]['caption'] == 'Не оценено: 1'
    assert report['table']['total_rows'] == 3
    assert report['table']['rows'][0]['fit_score'] == 0
    assert report['table']['rows'][0]['url'] is None
    assert report['table']['rows'][0]['availability'] == 'Неизвестно'
    assert report['meta']['timezone'] == 'Europe/Moscow'


def test_empty_is_live_and_selection_required_is_distinct():
    filters = BoardFilters(None, date(2026, 10, 15), date(2026, 10, 15))
    report = build_greenhouse_report(snapshot(candidate_id=None, total_rows=0, daily=[], rows=[], bands=[], points=[], boards=[]), filters)
    assert report['state'] == 'live'
    assert report['meta']['selection_required'] is True
    assert report['kpis'][0]['value'] == '—'


@pytest.mark.parametrize('kwargs', [dict(date_from=date(2026, 10, 16), date_to=date(2026, 10, 15)),
                                       dict(candidate_id="alpha';drop table vacancy;--"),
                                       dict(availability='active'), dict(date_to=date(2099, 1, 1))])
def test_invalid_filters(kwargs):
    args = dict(candidate_id='alpha', date_from=date(2026, 10, 13), date_to=date(2026, 10, 15))
    args.update(kwargs)
    with pytest.raises(ValueError):
        BoardFilters(**args)


@pytest.mark.parametrize('kwargs', [dict(page=-1), dict(sort_key='title;DROP'), dict(sort_direction='sideways')])
def test_invalid_paging(kwargs):
    with pytest.raises(ValueError):
        TablePage(**kwargs)


def test_page_does_not_bound_aggregates():
    report = build_greenhouse_report(snapshot(total_rows=250, rows=[]), BoardFilters('alpha', date(2026, 10, 13), date(2026, 10, 15)), TablePage(page=2))
    assert report['table']['page'] == 2
    assert report['table']['page_size'] == 100
    assert report['table']['total_rows'] == 250
    assert report['charts']['chart_series'][0]['series'][0]['y'] == [1, 0, 2]


def test_scatter_uses_deployed_jev_contract_without_rubric_series():
    stamp = datetime(2026, 10, 15, tzinfo=timezone.utc)
    report = build_greenhouse_report(snapshot(points=[
        dict(discovered_at=stamp, fit_score=50, fit_score_version='v1'),
        dict(discovered_at=stamp, fit_score=50, fit_score_version='v2'),
        dict(discovered_at=stamp, fit_score=0, fit_score_version=None)]),
        BoardFilters('alpha', date(2026, 10, 13), date(2026, 10, 15)))
    series = report['charts']['chart_series'][3]['series']
    assert [s['name'] for s in series] == ['Jev']
    assert len(series[0]['data']) == 3


def test_jev_report_uses_numeric_scores_and_client_sorts_complete_rows():
    rows = [dict(vacancy_id=str(i), fit_score=score, remote_work_readiness=None, board_token='acme')
            for i, score in enumerate([0, 1, 100, None])]
    report = build_greenhouse_report(snapshot(rows=rows, total_rows=4),
        BoardFilters('alpha', date(2026, 10, 13), date(2026, 10, 15)))
    fit = report['charts']['chart_series'][1]
    assert fit['x'] == ['0', '90']
    assert report['table']['client_sort'] is True
    assert len(report['table']['rows']) == 4
    assert [row['fit_score'] for row in report['table']['rows']] == [0, 1, 100, None]
    assert report['table']['columns'][-2]['key'] == 'fit_score'
    assert report['table']['columns'][-1]['key'] == 'remote_work_readiness'


def test_table_keeps_only_requested_columns():
    report = build_greenhouse_report(snapshot(), BoardFilters('alpha', date(2026, 10, 13), date(2026, 10, 15)))
    columns = report['table']['columns']
    assert [c['key'] for c in columns] == ['title', 'company', 'location', 'work_mode', 'fit_score', 'remote_work_readiness']
    readiness = columns[-1]
    assert readiness == {'key': 'remote_work_readiness', 'label': 'Международная удалёнка', 'kind': 'number',
                         'format': 'percent', 'sortable': True, 'filter': 'range', 'filterMin': 0, 'filterMax': 100}
    assert report['table']['rows'][0]['remote_work_readiness'] is None
    assert report['table']['rows'][0]['fit_score'] == 0


def test_score_distribution_uses_aggregate_for_entire_selection_not_current_page():
    report = build_greenhouse_report(snapshot(rows=[{'vacancy_id': 'page-row', 'fit_score': 0,
        'remote_work_readiness': None, 'board_token': None}], bands=[
            {'label': '0', 'count': 17}, {'label': '90', 'count': 6}]),
        BoardFilters('alpha', date(2026, 10, 13), date(2026, 10, 15)), TablePage(page=1))
    assert report['charts']['chart_series'][1]['x'] == ['0', '90']
    assert report['charts']['chart_series'][1]['series'][0]['y'] == [17, 6]
    assert report['table']['page'] == 1
    assert [row['vacancy_id'] for row in report['table']['rows']] == ['page-row']


def test_readiness_row_value_is_preserved_raw_in_report():
    fraction = 0.3141592653589793
    report = build_greenhouse_report(snapshot(rows=[dict(vacancy_id='ready', title='Remote',
        url='https://example.test/job', fit_score=None, remote_work_readiness=fraction, board_token=None)]),
        BoardFilters('alpha', date(2026, 10, 13), date(2026, 10, 15)))
    assert report['table']['rows'][0]['remote_work_readiness'] == fraction
    assert 'model' not in report['table']['rows'][0]
    assert 'rubric' not in report['table']['rows'][0]


def test_boards_horizontal_top_twenty_company_labels_and_other(monkeypatch):
    monkeypatch.setattr('job_machine.board.greenhouse.board_labels', lambda: {'token-0': 'Company Zero'})
    boards = [dict(token=f'token-{i}', company=f'Company {i:02}', count=30-i) for i in range(23)]
    report = build_greenhouse_report(snapshot(boards=list(reversed(boards))), BoardFilters('alpha', date(2026, 10, 13), date(2026, 10, 15)))
    chart = next(c for c in report['charts']['specs'] if c['id'] == 'boards')
    data = next(c for c in report['charts']['chart_series'] if c['id'] == 'boards')
    assert chart['encoding'] == 'hbar'
    assert chart['guard']['overflow'] == 21
    assert chart['guard']['flatCv'] == 0
    assert data['x'] == ['Company Zero'] + [f'Company {i:02}' for i in range(1, 20)] + ['Прочее']
    assert data['series'][0]['y'] == list(range(30, 10, -1)) + [27]
    assert sum(data['series'][0]['y']) == 437


def test_board_chart_small_empty_and_unknown_company(monkeypatch):
    monkeypatch.setattr('job_machine.board.greenhouse.board_labels', lambda: {})
    selection = BoardFilters('alpha', date(2026, 10, 13), date(2026, 10, 15))
    p = build_greenhouse_report(snapshot(boards=[dict(token='unlabelled-token', company=None, count=1)]), selection)
    data = p['charts']['chart_series'][2]
    assert data['x'] == ['Компания не указана']
    assert data['series'][0]['y'] == [1]
    assert build_greenhouse_report(snapshot(boards=[]), selection)['charts']['chart_series'][2]['x'] == []
    unknown = build_greenhouse_report(snapshot(boards=[dict(token=None, company='Do not attribute all unknown boards here', count=10)]), selection)
    assert unknown['charts']['chart_series'][2]['x'] == ['Компания не указана']
