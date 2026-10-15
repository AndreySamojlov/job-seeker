"""Pure HTML for source evidence and freshness."""
from datetime import datetime, timedelta, timezone
import html
from job_machine.ops.client import redact
from job_machine.ops.dashboard_state import BlockResult

MOSCOW = timezone(timedelta(hours=3), name='Europe/Moscow')
LABELS = {'summary':'Сводка состояний', 'blockers':'Блокировки заявок',
          'ready':'Очередь на одобрение', 'observations':'События', 'status':'Контейнеры'}


def esc(value) -> str:
    return html.escape('' if value is None else str(value))


def format_time(value: datetime) -> str:
    return value.astimezone(MOSCOW).isoformat(sep=' ', timespec='seconds') + ' (Europe/Moscow)'


def render_observer_status(blocks: dict[str, BlockResult]) -> str:
    parts = ['<section aria-label="Состояние и свидетельства"><h2>Состояние системы</h2>',
             '<p>Выполнение фоновой обработки сейчас: <strong>неизвестно</strong>. '
             'Доступность БД и контейнеров не доказывает полезную работу обработчиков.</p>']
    sources = []
    for name, block in blocks.items():
        label = LABELS.get(name, name)
        if block.state == 'unavailable':
            parts.append(f'<p class="observer-warning" role="status">{esc(label)}: сведения недоступны.</p>')
        elif block.state == 'stale':
            parts.append(f'<p class="observer-warning" role="status">{esc(label)}: устаревшие данные. Последний успешный снимок: '
                         f'{esc(format_time(block.fetched_at))}. Срок показа — не более 300 секунд.</p>')
        else:
            sources.append(f'<p>{esc(label)}: данные получены {esc(format_time(block.fetched_at))}.</p>')
        if block.error:
            sources.append(f'<details><summary>{esc(label)}: ошибка чтения источника</summary>'
                         f'<p>{esc(redact(block.error))}</p></details>')
    observation = blocks.get('observations')
    if observation and observation.state != 'unavailable':
        parts.append('<div class="observer-activity">')
        for kind, title in [('latest_event','Последнее зарегистрированное событие'),
                            ('latest_result','Последний полезный результат выбранных типов')]:
            row = observation.data.get(kind)
            detail = (f'{esc(row["event_type"])} · {esc(format_time(row["created_at"]))}' if row else
                      'Нет зарегистрированных событий выбранного вида')
            parts.append(f'<p>{title}: {detail}.</p>')
        parts.append('</div>')
        sources.append('<p>Полезные результаты: обнаружение и проверка вакансии, готовность пакета и формы. '
                     'Эта выборка не охватывает все виды работы системы.</p>')
    sources.append('<p>Сведения о последней технической ошибке недоступны. '
                   'Ошибки чтения страницы указаны отдельно.</p>')
    parts.append('<details class="observer-sources"><summary>Источники и ограничения наблюдения</summary>' +
                 ''.join(sources) + '</details></section>')
    return ''.join(parts)
