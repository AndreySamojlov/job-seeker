"""Separate S1 app. Run with uvicorn job_machine.board.app:create_app --factory."""
from datetime import date, datetime, timedelta, timezone
from contextlib import asynccontextmanager
import json
from importlib.metadata import version

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response
from fastapi.encoders import jsonable_encoder
from cockpit_engine.web.board_contract import BoardDomain, BoardSpec, BoardRefreshPolicy
from cockpit_engine.web.board_routes import register_board_routes

from job_machine.board.config import GreenhouseRepository
from job_machine.board.greenhouse import build_greenhouse_report
from job_machine.board.models import BoardFilters, MOSCOW, TablePage

from job_machine.board.read_budget import MAX_RESPONSE_BYTES, ReadBudget, ReadDeadline, SnapshotTooLarge, monotonic_ms
from job_machine.board.read_runtime import ReadCoordinator, PreparedReport, ReadBusy

class CandidateUnavailable(ValueError):
    pass


class InvalidReport(RuntimeError):
    pass


ENGINE_VERSION = '0.2.0a8'


def create_app(repository=None) -> FastAPI:
    if version('cockpit-engine') != ENGINE_VERSION:
        raise RuntimeError('Unsupported cockpit-engine version; expected ' + ENGINE_VERSION)
    repository = repository if repository is not None else GreenhouseRepository()
    coordinator = ReadCoordinator()
    @asynccontextmanager
    async def lifespan(app):
        yield
        await coordinator.aclose()
    app = FastAPI(title='Job Seeker Board', docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    register_board_routes(app, board=BoardSpec(key='job-board', title='Job Seeker', page_path='/',
        data_url='/api/board/greenhouse', refresh=BoardRefreshPolicy(), domains=(BoardDomain('greenhouse', 'Greenhouse'),)))

    @app.get('/healthz')
    async def health():
        return {'status': 'ok'}

    @app.get('/api/board/greenhouse')
    async def greenhouse(request: Request, domain: str = 'greenhouse', candidate_id: str | None = None,
                   discovered_from: date | None = None, discovered_to: date | None = None,
                   board: str | None = None, availability: str | None = None, column_filters: str = '{}',
                   page: int = Query(0, ge=0), sort_key: str = 'discovered_at', sort_direction: str = 'desc'):
        budget = ReadBudget()
        allowed = {'domain', 'candidate_id', 'discovered_from', 'discovered_to', 'board', 'availability', 'column_filters', 'page', 'sort_key', 'sort_direction'}
        if domain != 'greenhouse' or set(request.query_params) - allowed:
            raise HTTPException(422, 'Invalid selection')
        today = datetime.now(MOSCOW).date()
        try:
            filters = BoardFilters(candidate_id or None, discovered_from or today - timedelta(days=29),
                                   discovered_to or today, board or None, availability or None, column_filters)
            paging = TablePage(page, sort_key, sort_direction)
        except ValueError:
            raise HTTPException(422, 'Invalid selection') from None
        def prepare(budget):
            try:
                snapshot = repository.load(filters, paging, budget=budget)
            except ValueError:
                raise CandidateUnavailable() from None
            try:
                report = build_greenhouse_report(snapshot, filters, paging)
            except Exception:
                raise InvalidReport() from None
            report['meta']['fetched_at'] = datetime.now(timezone.utc).isoformat()
            report['meta']['snapshot_age_ms'] = max(0, int(monotonic_ms() - snapshot.stamp.monotonic_started_ms))
            try:
                body = json.dumps(jsonable_encoder(report), ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')
            except Exception:
                raise InvalidReport() from None
            if len(body) > MAX_RESPONSE_BYTES:
                raise SnapshotTooLarge()
            budget.check_response_deadline()
            return PreparedReport(body)
        try:
            result = await coordinator.run(prepare, budget=budget)
        except CandidateUnavailable:
            raise HTTPException(422, 'candidate_unavailable') from None
        except SnapshotTooLarge:
            return JSONResponse(dict(schema_version=1, state='unavailable', code='snapshot_too_large',
                                     detail='Выборка слишком велика для безопасного чтения'),
                                status_code=503, headers={'Cache-Control': 'no-store'})
        except InvalidReport:
            return JSONResponse(dict(schema_version=1, state='unavailable', code='invalid_report', detail='Данные недоступны'), status_code=500, headers={'Cache-Control': 'no-store'})
        except ReadDeadline:
            return JSONResponse(dict(schema_version=1, state='unavailable', code='snapshot_timeout',
                                     detail='Не удалось полностью загрузить выборку за отведённое время'),
                                status_code=503, headers={'Cache-Control': 'no-store'})
        except Exception as exc:
            return JSONResponse(dict(schema_version=1, state='unavailable', detail='Данные недоступны',
                                     code='read_busy' if isinstance(exc, ReadBusy) else 'source_unavailable'),
                                status_code=503, headers={'Cache-Control': 'no-store', **({'Retry-After': '60'} if isinstance(exc, ReadBusy) else {})})
        return Response(result.body, media_type='application/json', headers={'Cache-Control': 'no-store'})

    return app
