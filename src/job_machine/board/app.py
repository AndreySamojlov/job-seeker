"""Separate S1 app. Run with uvicorn job_machine.board.app:create_app --factory."""
from datetime import date, datetime, timedelta
from importlib.metadata import version

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from cockpit_engine.web.board_contract import BoardDomain, BoardSpec
from cockpit_engine.web.board_routes import register_board_routes

from job_machine.board.config import GreenhouseRepository
from job_machine.board.greenhouse import build_greenhouse_report
from job_machine.board.models import BoardFilters, MOSCOW, TablePage

ENGINE_VERSION = '0.2.0a1'


def create_app(repository=None) -> FastAPI:
    if version('cockpit-engine') != ENGINE_VERSION:
        raise RuntimeError('Unsupported cockpit-engine version; expected ' + ENGINE_VERSION)
    repository = repository if repository is not None else GreenhouseRepository()
    app = FastAPI(title='Job Seeker Board', docs_url=None, redoc_url=None, openapi_url=None)
    register_board_routes(app, board=BoardSpec(key='job-board', title='Job Seeker', page_path='/',
        data_url='/api/board/greenhouse', domains=(BoardDomain('greenhouse', 'Greenhouse'),)))

    @app.get('/healthz')
    def health():
        return {'status': 'ok'}

    @app.get('/api/board/greenhouse')
    def greenhouse(request: Request, domain: str = 'greenhouse', candidate_id: str | None = None,
                   discovered_from: date | None = None, discovered_to: date | None = None,
                   board: str | None = None, availability: str | None = None,
                   page: int = Query(0, ge=0), sort_key: str = 'discovered_at', sort_direction: str = 'desc'):
        allowed = {'domain', 'candidate_id', 'discovered_from', 'discovered_to', 'board', 'availability', 'page', 'sort_key', 'sort_direction'}
        if domain != 'greenhouse' or set(request.query_params) - allowed:
            raise HTTPException(422, 'Invalid selection')
        today = datetime.now(MOSCOW).date()
        try:
            filters = BoardFilters(candidate_id or None, discovered_from or today - timedelta(days=29),
                                   discovered_to or today, board or None, availability or None)
            paging = TablePage(page, sort_key, sort_direction)
        except ValueError:
            raise HTTPException(422, 'Invalid selection') from None
        try:
            snapshot = repository.load(filters, paging)
        except ValueError:
            raise HTTPException(422, 'Candidate unavailable') from None
        except Exception:
            return JSONResponse(dict(schema_version=1, state='unavailable', detail='Данные недоступны'),
                                status_code=503, headers={'Cache-Control': 'no-store'})
        return JSONResponse(jsonable_encoder(build_greenhouse_report(snapshot, filters, paging)),
                            headers={'Cache-Control': 'no-store'})

    return app
