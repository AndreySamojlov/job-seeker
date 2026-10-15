"""Local read-only dashboard backed by the existing lab-do runtime over SSH."""
from datetime import datetime, timezone
import html
import logging
import time
import threading
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware
from job_machine.dashboard.render import render_dashboard
from job_machine.ops.client import RuntimeClient, TransientTransportError, redact
from job_machine.ops.tunnel_dashboard import TunnelDashboardClient

logger = logging.getLogger(__name__)

def create_app(client=None):
    runtime = client if client is not None else TunnelDashboardClient()
    snapshot = None
    snapshot_lock = threading.Lock()
    app = FastAPI(title='Job Machine — lab-do', docs_url=None, redoc_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1','localhost','testserver'])

    @app.get('/healthz')
    def healthz():
        return {'status':'ok','scope':'local dashboard; use / for runtime connectivity'}

    @app.get('/', response_class=HTMLResponse)
    def dashboard():
        nonlocal snapshot
        stage = 'summary'
        def read(operation, *args, **kwargs):
            try:
                return operation(*args, **kwargs)
            except TransientTransportError as exc:
                logger.warning('Retrying dashboard read at %s once: %s', stage, redact(str(exc)))
                return operation(*args, **kwargs)
        try:
            summary = read(runtime.data, 'summary')
            funnel = {}
            for row in summary:
                funnel.setdefault(row['entity'], {})[row['state']] = row['count']
            stage = 'blockers'
            blockers = read(runtime.data, 'blockers')
            stage = 'ready'
            ready = read(runtime.data, 'ready', limit=50)
        except (RuntimeError, ValueError) as exc:
            logger.warning('Dashboard runtime read failed at %s: %s', stage, redact(str(exc)))
            with snapshot_lock:
                cached = snapshot
            if cached is not None and time.monotonic() - cached[0] <= 300:
                notice = ('<div role="alert" style="background:#fff2c2;color:#332500;padding:16px">'
                          '<strong>Источник временно недоступен. Последний успешный снимок: '
                          + html.escape(cached[1]) + '</strong>. Данные сейчас не обновлены; '
                          'снимок показывается не дольше пяти минут после получения.</div>')
                return HTMLResponse(cached[2].replace('<body>', '<body>' + notice),
                                    headers={'X-Job-Machine-Data':'stale','Cache-Control':'no-store'})
            return HTMLResponse('<h1>Job Machine — lab-do недоступен</h1><p>Данные не получены. '
                                'Ошибка получения данных записана в журнал для диагностики агентом. '
                                'Следующее открытие страницы повторит чтение.</p>', status_code=503)
        stage = 'status'
        service_warning = ''
        try:
            services = read(runtime.status)
        except (RuntimeError, ValueError) as exc:
            logger.warning('Dashboard container status unavailable: %s', redact(str(exc)))
            services = []
            service_warning = '<p role="status">Статус контейнеров недоступен; данные заявок получены из БД.</p>'
        page = render_dashboard(funnel, blockers, ready, generated_at=datetime.now(timezone.utc))
        rows = ''.join('<tr>' + ''.join('<td>' + html.escape(str(value)) + '</td>' for value in
                       (s['Name'],s['ImageTag'],s['State']['Status'],s['State']['Health'])) + '</tr>' for s in services)
        extra = ('<h2>Существующий инстанс lab-do</h2><table><tr><th>Сервис</th><th>Образ</th>'
                 '<th>Состояние</th><th>Health</th></tr>' + rows + '</table>' + service_warning +
                 '<p>Только чтение. Production не переключён. Операции управления доступны агенту через ops CLI/MCP.</p>')
        attempts = ', '.join(f'{html.escape(k)}: {v}' for k,v in funnel.get('attempt',{}).items())
        page = page.replace('</body>', extra + '<h2>Попытки отправки</h2><p>' + attempts + '</p></body>')
        with snapshot_lock:
            snapshot = (time.monotonic(), datetime.now(timezone.utc).isoformat(), page)
        return HTMLResponse(page, headers={'X-Job-Machine-Data':'live','Cache-Control':'no-store'})

    return app

app = create_app()
