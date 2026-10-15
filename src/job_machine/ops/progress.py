"""Current-state distributions. Each entity has its own unit and scale."""
from job_machine.ops.observer_render import esc, format_time

ENTITIES = (
    ('vacancy', 'Вакансии', 'вакансий', 'vacancy.state'),
    ('application', 'Заявки', 'заявок', 'application.state'),
    ('attempt', 'Попытки отправки', 'попыток', 'submission_attempt.status'),
)
LABELS = {
    'discovered':'Найдены', 'verified':'Проверены', 'triaged':'Оценены',
    'skipped':'Пропущены', 'needs_package':'Ожидают пакет', 'package_ready':'Пакет готов',
    'pre_submit_ready':'Форма готова', 'awaiting_approval':'Ожидают одобрение',
    'approved':'Одобрены', 'submitting':'Отправка', 'submitted':'Отправлены',
    'fill_blocked':'Заполнение заблокировано', 'submit_blocked':'Отправка заблокирована',
    'agent_fill_pending':'Ожидают агента', 'submit_unknown':'Исход отправки неизвестен',
    'unknown':'Неизвестно', 'failed':'Failed — зафиксированное состояние',
    'claimed':'Зарезервированы', 'clicking':'Начат клик', 'confirmed':'Подтверждены',
    'not_submitted':'Не отправлены', None:'Состояние не записано',
}

PROGRESS_STYLE = """
body{max-width:1320px;margin:0 auto;padding:28px;box-sizing:border-box}
.progress-section{margin:24px 0 32px}.progress-section>h2{font-size:22px;margin:0 0 8px;color:#f0f4fa}
.progress-note{font-size:13px;color:#9ca9bb;line-height:1.55;margin:6px 0 16px}
.progress-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:18px}
.progress-chart{--bar:#4cc9dc;background:#171c25;border:1px solid #303b4d;border-radius:14px;padding:20px;min-width:0}
.progress-chart[data-entity=application]{--bar:#b497ff}.progress-chart[data-entity=attempt]{--bar:#54d6aa}
.progress-chart h3{margin:0;font-size:17px;color:#edf2fa}.progress-total{font-size:34px;font-weight:650;margin:12px 0 0;font-variant-numeric:tabular-nums}
.progress-unit{font-size:12px;color:#9ca9bb;font-weight:400;margin-left:7px}
.progress-source{font-size:11px;color:#9ca9bb;margin:8px 0 18px;overflow-wrap:anywhere}
.progress-row{margin-top:16px}.progress-row-head{display:flex;gap:12px;justify-content:space-between;align-items:start;font-size:13px}
.progress-label{min-width:0;overflow-wrap:anywhere}.progress-value{font-weight:650;font-variant-numeric:tabular-nums;white-space:nowrap}
.progress-code{display:block;color:#9ca9bb;font-size:11px;margin-top:3px;overflow-wrap:anywhere}
.progress-track{height:12px;border-radius:4px;background:#293342;margin-top:8px;overflow:hidden}
.progress-bar{height:100%;background:var(--bar);border-radius:4px}
.observer-sources{font-size:12px;color:#a5b1c1;margin:14px 0}.observer-sources>summary{cursor:pointer;padding:8px 0}
.observer-sources p{margin:6px 0}.observer-activity{display:grid;grid-template-columns:1fr 1fr;gap:12px;line-height:1.5}
.observer-activity p{margin:0;padding:12px 14px;background:#171c25;border-left:3px solid #536782;border-radius:4px;font-size:13px}
.observer-warning{padding:10px 14px;border-left:3px solid #e7b868;background:#30291d;border-radius:4px;font-size:13px}
@media(max-width:900px){.progress-grid{grid-template-columns:1fr}.observer-activity{grid-template-columns:1fr}}
@media(max-width:480px){body{padding:16px}.progress-chart{padding:16px}}
"""


def build_progress(rows: list[dict]) -> list[dict]:
    grouped = {entity:{} for entity, *_ in ENTITIES}
    if not isinstance(rows, list):
        raise ValueError('Invalid summary response')
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('Invalid summary row')
        entity, state, count = row.get('entity'), row.get('state'), row.get('count')
        if (not isinstance(entity, str) or entity not in grouped
                or not isinstance(state, (str, type(None))) or type(count) is not int or count < 0):
            raise ValueError('Invalid summary row')
        grouped[entity][state] = grouped[entity].get(state, 0) + count
    charts = []
    for entity, title, unit, source in ENTITIES:
        values = grouped[entity]
        maximum = max(values.values(), default=0)
        ordered = sorted(values.items(), key=lambda pair:(-pair[1], str(pair[0])))
        charts.append(dict(entity=entity, title=title, unit=unit, source=source,
                           total=sum(values.values()), rows=[
                               dict(state=state, label=LABELS.get(state, state), count=count,
                                    width=round(count / maximum * 100, 3) if maximum else 0)
                               for state,count in ordered]))
    return charts


def render_progress(rows: list[dict], *, state='live', fetched_at=None) -> str:
    parts = ['<section class="progress-section" aria-label="Графики прогресса">'
             '<h2>Распределение по текущим состояниям</h2>'
             '<p class="progress-note">Все записи · Текущее состояние · Отдельная единица счёта в каждом графике. '
             'Это распределения, а не сквозная конверсия. Длина столбца сравнивается с наибольшим значением своего графика.</p>']
    if state == 'stale':
        parts.append('<p class="observer-warning">Графики показывают устаревший снимок; источник сейчас недоступен.</p>')
    if fetched_at:
        parts.append(f'<p class="progress-note">Сводка получена: {esc(format_time(fetched_at))}</p>')
    parts.append('<div class="progress-grid">')
    for chart in build_progress(rows):
        parts.append(f'<section class="progress-chart" data-entity="{chart["entity"]}" '
                     f'data-total="{chart["total"]}" aria-label="{chart["title"]}">'
                     f'<h3>{chart["title"]}</h3><p class="progress-total">{chart["total"]}'
                     f'<span class="progress-unit">{chart["unit"]}</span></p>'
                     f'<p class="progress-source">Источник: {chart["source"]}. Один объект учитывается в одном текущем состоянии.</p>')
        if not chart['rows']:
            parts.append('<p class="empty">Нет записей</p>')
        for row in chart['rows']:
            code = 'NULL' if row['state'] is None else row['state']
            parts.append(f'<div class="progress-row" data-state="{esc(code)}" data-count="{row["count"]}">'
                         f'<div class="progress-row-head"><span class="progress-label">{esc(row["label"])}'
                         f'<span class="progress-code">{esc(code)}</span></span>'
                         f'<span class="progress-value">{row["count"]}</span></div>'
                         f'<div class="progress-track" role="img" aria-label="{esc(code)}: {row["count"]}">'
                         f'<div class="progress-bar" style="width:{row["width"]}%"></div></div></div>')
        parts.append('</section>')
    parts.append('</div></section>')
    return ''.join(parts)
