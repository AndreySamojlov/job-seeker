from datetime import date, datetime, timezone

import pytest

from job_machine.board.models import BoardFilters, GreenhouseSnapshot, TablePage
from job_machine.board.greenhouse import build_greenhouse_report


def snapshot(**changes):
    values = dict(candidate_id='alpha', candidates=[{'candidate_id': 'alpha', 'name': 'Alpha'}],
                  board_options=['acme'], total_rows=3, unknown_board=1, unscored=1,
                  daily=[{'day': date(2026, 10, 13), 'count': 1}, {'day': date(2026, 10, 15), 'count': 2}],
                  bands=[{'label': 'low · v1', 'count': 1}, {'label': 'high · v2', 'count': 1}, {'label': 'Не оценено', 'count': 1}],
                  boards=[{'token': 'acme', 'count': 2}, {'token': None, 'count': 1}],
                  points=[{'discovered_at': datetime(2026, 10, 13, tzinfo=timezone.utc), 'fit_score': 0},
                          {'discovered_at': datetime(2026, 10, 15, tzinfo=timezone.utc), 'fit_score': 90}],
                  rows=[{'vacancy_id': 'synthetic', 'title': '<img src=x>', 'url': 'javascript:alert(1)', 'fit_score': 0, 'board_token': None}],
                  fetched_at=datetime(2026, 10, 15, tzinfo=timezone.utc))
    values.update(changes)
    return GreenhouseSnapshot(**values)


def test_report_preserves_zero_unknowns_versions_and_calendar_days():
    report = build_greenhouse_report(snapshot(), BoardFilters('alpha', date(2026, 10, 13), date(2026, 10, 15)))
    assert [k['value'] for k in report['kpis']] == ['1', 'Нет данных', '1', 'Нет данных']
    assert report['charts']['chart_series'][0]['series'][0]['y'] == [1, 0, 2]
    assert report['charts']['chart_series'][1]['x'] == ['low · v1', 'high · v2', 'Не оценено']
    assert report['charts']['chart_series'][3]['series'][0]['data'][0]['y'] == 0
    assert '1' in report['charts']['specs'][3]['caption']
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


def test_scatter_keeps_rubric_versions_distinguishable():
    stamp = datetime(2026, 10, 15, tzinfo=timezone.utc)
    report = build_greenhouse_report(snapshot(points=[
        dict(discovered_at=stamp, fit_score=50, fit_score_version='v1'),
        dict(discovered_at=stamp, fit_score=50, fit_score_version='v2'),
        dict(discovered_at=stamp, fit_score=0, fit_score_version=None)]),
        BoardFilters('alpha', date(2026, 10, 13), date(2026, 10, 15)))
    series = report['charts']['chart_series'][3]['series']
    assert {s['name'] for s in series} == {'Фит · v1', 'Фит · v2', 'Фит · Версия неизвестна'}
    assert sum(len(s['data']) for s in series) == 3


def test_table_keeps_only_requested_columns():
    report = build_greenhouse_report(snapshot(), BoardFilters('alpha', date(2026, 10, 13), date(2026, 10, 15)))
    assert [c['key'] for c in report['table']['columns']] == ['title', 'company', 'location', 'work_mode', 'fit_score']


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
