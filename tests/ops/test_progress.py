import pytest


def test_progress_keeps_entity_units_separate_and_preserves_unknowns():
    from job_machine.ops.progress import build_progress
    rows = [dict(entity='vacancy', state='verified', count=100),
            dict(entity='application', state='submitted', count=4),
            dict(entity='attempt', state='confirmed', count=6),
            dict(entity='application', state='future_state', count=2),
            dict(entity='application', state=None, count=1)]
    charts = build_progress(rows)
    assert [c['entity'] for c in charts] == ['vacancy','application','attempt']
    assert [c['total'] for c in charts] == [100,7,6]
    assert {r['state']:r['count'] for r in charts[1]['rows']} == {'submitted':4,'future_state':2,None:1}
    assert next(r for r in charts[1]['rows'] if r['state']=='submitted')['width'] == 100
    assert next(r for r in charts[1]['rows'] if r['state']=='future_state')['width'] == 50


def test_zero_and_empty_summary_are_not_missing_data():
    from job_machine.ops.progress import build_progress, render_progress
    charts = build_progress([dict(entity='vacancy', state='verified', count=0)])
    assert charts[0]['rows'][0]['width'] == 0
    assert charts[0]['rows'][0]['count'] == 0
    page = render_progress([])
    assert page.count('Нет записей') == 3
    assert 'Сведения недоступны' not in page


@pytest.mark.parametrize('row', [
    dict(entity='vacancy',state='verified',count=-1),
    dict(entity='vacancy',state='verified',count=True),
    dict(entity='vacancy',state='verified',count=1.5),
    dict(entity='vacancy',state=[],count=1),
    dict(entity='wrong',state='verified',count=1),
])
def test_invalid_summary_cannot_produce_a_chart(row):
    from job_machine.ops.progress import build_progress
    with pytest.raises(ValueError): build_progress([row])


def test_bar_chart_has_counts_units_scope_and_escaped_states():
    from job_machine.ops.progress import render_progress
    page = render_progress([dict(entity='application',state='<script>',count=3)])
    assert 'class="progress-bar"' in page
    assert 'Вакансии' in page and 'Заявки' in page and 'Попытки отправки' in page
    assert 'Все записи' in page and 'Текущее состояние' in page
    assert 'application.state' in page
    assert 'aria-label=' in page
    assert '&lt;script&gt;' in page and '<script>' not in page


def test_duplicate_state_counts_are_combined_not_overwritten():
    from job_machine.ops.progress import build_progress
    charts = build_progress([dict(entity='vacancy',state='verified',count=3),
                             dict(entity='vacancy',state='verified',count=2)])
    assert charts[0]['total']==5
    assert charts[0]['rows'][0]['count']==5
