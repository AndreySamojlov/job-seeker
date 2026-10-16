"""Pure Greenhouse calculations and portable board-v1 configuration."""
from datetime import timedelta
import json
from pathlib import Path
from urllib.parse import urlsplit

from job_machine.board.models import BoardFilters, GreenhouseSnapshot, TablePage
from job_machine.board.context import canonical_context
from job_machine.board.read_budget import monotonic_ms
from job_machine.board.column_filters import parse_column_filters


def board_labels():
    registry = Path(__file__).resolve().parents[3] / 'config' / 'sources.json'
    if not registry.exists():
        return {}
    sources = json.loads(registry.read_text(encoding='utf-8')).get('sources', [])
    return {s['token']: s['label'].strip() for s in sources
            if s.get('ats') == 'greenhouse' and s.get('token') and isinstance(s.get('label'), str) and s['label'].strip()}


def safe_url(value):
    try:
        parsed = urlsplit(value or '')
        if parsed.scheme in ('https', 'http') and parsed.hostname and not parsed.username and not parsed.password:
            return value
    except ValueError:
        pass
    return None


def build_greenhouse_report(snapshot: GreenhouseSnapshot, filters: BoardFilters, table_page: TablePage = TablePage()) -> dict:
    labels = board_labels()
    def label(token):
        return f'{labels[token]} ({token})' if token in labels and labels[token] != token else token or 'Борд неизвестен'
    days = (filters.date_to - filters.date_from).days + 1
    counts = {row['day']: row['count'] for row in snapshot.daily}
    dates = [filters.date_from + timedelta(days=i) for i in range(days)]
    daily = [counts.get(day, 0) for day in dates]
    required = snapshot.candidate_id is None
    known_boards = sum(row['token'] is not None for row in snapshot.boards)
    ranked_boards = sorted(snapshot.boards, key=lambda r: (-r['count'], r['token'] or ''))
    board_names = [(labels.get(r['token']) or (r.get('company') or '').strip() or 'Компания не указана')
                   if r['token'] is not None else 'Компания не указана'
                   for r in ranked_boards[:20]]
    board_counts = [r['count'] for r in ranked_boards[:20]]
    if len(ranked_boards) > 20:
        board_names.append('Прочее')
        board_counts.append(sum(r['count'] for r in ranked_boards[20:]))
    by_version = {}
    for point in snapshot.points:
        rubric = point.get('fit_score_version') or 'Версия неизвестна'
        by_version.setdefault(rubric, []).append(dict(x=int(point['discovered_at'].timestamp() * 1000), y=point['fit_score']))
    series = [
        dict(id='timeline', x=[d.isoformat() for d in dates], axis='time', series=[dict(name='Обнаружено', y=daily)]),
        dict(id='fit', x=[r['label'] for r in snapshot.bands], series=[dict(name='Вакансии', y=[r['count'] for r in snapshot.bands])]),
        dict(id='boards', x=board_names, series=[dict(name='Вакансии', y=board_counts)]),
        dict(id='dates', series=[dict(name=f'Фит · {rubric}', data=points) for rubric, points in sorted(by_version.items())]),
    ]
    rows = []
    for source in snapshot.rows:
        row = dict(source)
        row.update(vacancy_id=str(row['vacancy_id']), url=safe_url(row.get('url')),
                   board_token=label(row.get('board_token')), availability='Неизвестно')
        # verified_at is intentionally not relabeled as an availability check date.
        row['availability_checked_at'] = None
        rows.append(row)
    return dict(schema_version=1, state='live',
        meta=dict(domain='greenhouse', context=canonical_context(filters, table_page, snapshot.candidate_id),
                  read_id=snapshot.read_id, snapshot_at=snapshot.stamp.snapshot_at.isoformat(),
                  snapshot_age_ms=max(0, int(monotonic_ms() - snapshot.stamp.monotonic_started_ms)),
                  filters=dict(candidate_id=snapshot.candidate_id,
                  discovered_from=filters.date_from.isoformat(), discovered_to=filters.date_to.isoformat(),
                  board=filters.board or '', availability=filters.availability or ''),
                  timezone='Europe/Moscow', fetched_at=snapshot.fetched_at.isoformat(), selection_required=required,
                  unknown_board=snapshot.unknown_board, unscored=snapshot.unscored),
        filters=[dict(key='candidate_id', label='Кандидат', kind='select', value=snapshot.candidate_id or '',
                      options=[dict(value='', label='Выберите кандидата')] + [dict(value=c['candidate_id'], label=c['name']) for c in snapshot.candidates]),
                 dict(key='discovered_from', context_key='date_from', label='Обнаружены с', kind='date', value=filters.date_from.isoformat()),
                 dict(key='discovered_to', context_key='date_to', label='Обнаружены по', kind='date', value=filters.date_to.isoformat()),
                 dict(key='board', label='Борд', kind='select', value=filters.board or '',
                      options=[dict(value='', label='Все борды')] + [dict(value=b, label=label(b)) for b in snapshot.board_options]),
                 dict(key='availability', label='Доступность', kind='select', value=filters.availability or '',
                      options=[dict(value='', label='Все'), dict(value='unknown', label='Неизвестно')])],
        kpis=[dict(label='Борды с вакансиями', value='—' if required else str(known_boards), sub=f'Борд не определён: {snapshot.unknown_board}'),
              dict(label='Подтверждены при проверке', value='Нет данных'),
              dict(label='В среднем новых в день', value='—' if required else f'{snapshot.total_rows / days:.2f}'.rstrip('0').rstrip('.').replace('.', ','),
                   element=dict(kind='line', data=daily, tip='Впервые обнаружены по календарным дням')),
              dict(label='Средний срок жизни', value='Нет данных')],
        charts=dict(specs=[dict(id='timeline', title='Обнаруженные по дням', encoding='bar', unit='qty', primary=True),
                          dict(id='fit', title='Распределение по фиту', encoding='pie', unit='qty'),
                          dict(id='boards', title='Вакансии по компаниям', encoding='hbar', unit='qty',
                               guard=dict(overflow=21, expandedOverflow=21, flatCv=0),
                               caption='20 крупнейших бордов; остальные — Прочее'),
                          dict(id='dates', title='Дата обнаружения и фит', encoding='date-scatter', yMin=0, yMax=100,
                               xLabel='Дата обнаружения', yLabel='Фит', caption=f'Не оценено: {snapshot.unscored}')], chart_series=series),
        table=dict(columns=[dict(key=key, label=title, kind=kind, filter='range' if kind == 'number' else 'text',
                                 **({'filterMin': 0, 'filterMax': 100} if kind == 'number' else {'filterMaxLength': 200}),
                                 **({'href_key': 'url'} if key == 'title' else {}))
                   for key, title, kind in [('title', 'Вакансия', 'link'), ('company', 'Компания', 'text'),
                    ('location', 'Локация', 'text'), ('work_mode', 'Формат', 'text'), ('fit_score', 'Фит', 'number')]],
                   filter_param='column_filters', filter_context_key='column_filters', filters=parse_column_filters(filters.column_filters),
                   row_key='vacancy_id', rows=rows, total_rows=snapshot.total_rows, page=table_page.page, page_size=100))
