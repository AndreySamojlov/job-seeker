"""Local read-only dashboard backed by the existing lab-do runtime."""
import logging
import time
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware
from job_machine.dashboard.render import _STYLE, _funnel_html, _blockers_html, _ready_html
from job_machine.ops.client import TransientTransportError, redact
from job_machine.ops.dashboard_state import SnapshotStore, page_outcome
from job_machine.ops.observations import normalize_observations
from job_machine.ops.observer_render import esc, render_observer_status
from job_machine.ops.tunnel_dashboard import TunnelDashboardClient

logger = logging.getLogger(__name__)


def _validated(name, rows):
    if name == 'observations':
        return normalize_observations(rows)
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError('Invalid source response')
    for row in rows:
        if name == 'summary':
            if (not isinstance(row.get('entity'), str) or not isinstance(row.get('state'), (str, type(None)))
                    or type(row.get('count')) is not int or row['count'] < 0):
                raise ValueError('Invalid summary row')
        elif name == 'status':
            if (not isinstance(row.get('Name'), str) or not isinstance(row.get('ImageTag'), str)
                    or not isinstance(row.get('State'), dict)
                    or not isinstance(row['State'].get('Status'), str)):
                raise ValueError('Invalid container status row')
        elif name == 'ready' and not isinstance(row.get('url', ''), (str, type(None))):
            raise ValueError('Invalid vacancy URL')
    return rows


def create_app(client=None):
    runtime = client if client is not None else TunnelDashboardClient()
    snapshots = SnapshotStore(monotonic=lambda: time.monotonic())
    app = FastAPI(title='Job Machine — lab-do', docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1','localhost','testserver'])

    @app.get('/healthz')
    def healthz():
        return {'status':'ok','scope':'local dashboard; use / for runtime connectivity'}

    @app.get('/', response_class=HTMLResponse)
    def dashboard():
        def load(name):
            def read():
                if name == 'status':
                    return _validated(name, runtime.status())
                return _validated(name, runtime.data(name, **({'limit':50} if name == 'ready' else {})))
            try:
                return read()
            except TransientTransportError as exc:
                logger.warning('Retrying dashboard read at %s once: %s', name, redact(str(exc)))
                return read()

        blocks = {name:snapshots.read(name, lambda name=name:load(name))
                  for name in ('summary','blockers','ready','observations','status')}
        blocks = snapshots.expire(blocks)
        code, outcome = page_outcome(blocks)
        page = ('<!DOCTYPE html><html lang="ru"><head><meta charset="utf-8">'
                '<meta name="viewport" content="width=device-width, initial-scale=1">'
                '<meta http-equiv="refresh" content="30">'
                f'<style>{_STYLE}table{{display:block;max-width:100%;overflow-x:auto}}'
                'p,td{overflow-wrap:anywhere}</style><title>Job Machine — Observer</title></head><body>'
                '<h1>Job Machine — lab-do</h1>' + render_observer_status(blocks))
        funnel = {}
        if blocks['summary'].state != 'unavailable':
            for row in blocks['summary'].data:
                funnel.setdefault(row['entity'], {})[row['state'] or 'unknown'] = row['count']
            page += '<h2>Состояния вакансий и заявок</h2><p>Текущие состояния разных сущностей; не сквозная конверсия.</p>' + _funnel_html(funnel)
            attempts = ', '.join(f'{esc(k)}: {esc(v)}' for k,v in funnel.get('attempt', {}).items())
            page += '<h2>Попытки отправки</h2><p>' + (attempts or 'Нет записей') + '</p>'
        else:
            page += '<h2>Состояния вакансий и заявок</h2><p>Сведения недоступны.</p>'
        for name,title,render in [('blockers','Блокеры заявок',_blockers_html),
                                   ('ready','Очередь на одобрение',_ready_html)]:
            page += f'<h2>{title}</h2>'
            page += render(blocks[name].data) if blocks[name].state != 'unavailable' else '<p>Сведения недоступны.</p>'
        page += '<h2>Существующий инстанс lab-do</h2>'
        if blocks['status'].state == 'unavailable':
            page += '<p role="status">Статус контейнеров недоступен.</p>'
        else:
            page += '<table><tr><th>Сервис</th><th>Образ</th><th>Состояние</th><th>Health</th></tr>'
            for service in blocks['status'].data:
                values = (service['Name'],service['ImageTag'],service['State']['Status'],
                          service['State'].get('Health') or 'неизвестно (нет сведений healthcheck)')
                page += '<tr>' + ''.join(f'<td>{esc(value)}</td>' for value in values) + '</tr>'
            page += '</table><p>Отсутствующие сервисы не считаются здоровыми; состояние обработки неизвестно.</p>'
        page += '<p>Только чтение. Production не переключён. Операции управления доступны агенту через ops CLI/MCP.</p></body></html>'
        return HTMLResponse(page,status_code=code,headers={'X-Job-Machine-Data':outcome,'Cache-Control':'no-store'})

    return app


app = create_app()
