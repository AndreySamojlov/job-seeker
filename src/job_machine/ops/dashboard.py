"""Local read-only dashboard backed by the existing lab-do runtime over SSH."""
from datetime import datetime, timezone
import html
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware
from job_machine.dashboard.render import render_dashboard
from job_machine.ops.client import RuntimeClient

def create_app(client=None):
    runtime = client if client is not None else RuntimeClient()
    app = FastAPI(title='Job Machine — lab-do', docs_url=None, redoc_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1','localhost','testserver'])

    @app.get('/healthz')
    def healthz():
        return {'status':'ok','scope':'local dashboard; use / for runtime connectivity'}

    @app.get('/', response_class=HTMLResponse)
    def dashboard():
        try:
            summary = runtime.data('summary')
            funnel = {}
            for row in summary:
                funnel.setdefault(row['entity'], {})[row['state']] = row['count']
            blockers = runtime.data('blockers')
            ready = runtime.data('ready', limit=50)
            services = runtime.status()
        except (RuntimeError, ValueError):
            return HTMLResponse('<h1>Job Machine — lab-do недоступен</h1><p>Данные не получены. '
                                'Проверьте SSH и состояние сервисов через ops status.</p>', status_code=503)
        page = render_dashboard(funnel, blockers, ready, generated_at=datetime.now(timezone.utc))
        rows = ''.join('<tr>' + ''.join('<td>' + html.escape(str(value)) + '</td>' for value in
                       (s['Name'],s['ImageTag'],s['State']['Status'],s['State']['Health'])) + '</tr>' for s in services)
        extra = ('<h2>Существующий инстанс lab-do</h2><table><tr><th>Сервис</th><th>Образ</th>'
                 '<th>Состояние</th><th>Health</th></tr>' + rows + '</table>'
                 '<p>Только чтение. Production не переключён. Операции управления доступны агенту через ops CLI/MCP.</p>')
        attempts = ', '.join(f'{html.escape(k)}: {v}' for k,v in funnel.get('attempt',{}).items())
        return page.replace('</body>', extra + '<h2>Попытки отправки</h2><p>' + attempts + '</p></body>')

    return app

app = create_app()
