from datetime import date

from fastapi.testclient import TestClient
import pytest

from job_machine.board.app import create_app
from job_machine.board.models import GreenhouseSnapshot


class Repository:
    def __init__(self): self.calls = []
    def load(self, filters, page, *, budget=None):
        self.calls.append((filters, page))
        if filters.board == 'fail':
            raise RuntimeError('postgresql://admin:secret@private/database')
        return GreenhouseSnapshot(candidate_id='alpha', candidates=[dict(candidate_id='alpha', name='Alpha')])


def test_installed_engine_page_and_live_empty_without_dsn(monkeypatch):
    monkeypatch.delenv('DATABASE_URL', raising=False)
    repository = Repository()
    with TestClient(create_app(repository)) as client:
        assert client.get('/healthz').json() == {'status': 'ok'}
        page = client.get('/')
        assert page.status_code == 200 and '/cockpit-assets/' in page.text
        assert client.get('/cockpit-assets/board-runtime.js').status_code == 200
        response = client.get('/api/board/greenhouse')
        assert response.status_code == 200
        assert response.json()['state'] == 'live'
        assert response.json()['table']['total_rows'] == 0
        assert repository.calls[0][0].date_to == date.today()
        assert client.post('/api/board/greenhouse').status_code == 405
        assert client.get('/v1/mp-cockpit/report').status_code == 404


@pytest.mark.parametrize('query', ['domain=telegram', 'candidate_id=%27DROP', 'discovered_from=wrong',
    'discovered_from=2026-10-15&discovered_to=2026-10-14', 'discovered_to=2099-01-01',
    'page=-1', 'sort_key=url', 'sort_direction=wrong', 'availability=active', 'extra=unknown'])
def test_invalid_input_never_reaches_repository(query):
    repository = Repository()
    with TestClient(create_app(repository)) as client:
        assert client.get('/api/board/greenhouse?' + query).status_code == 422
        assert repository.calls == []


def test_source_error_is_sanitized_503_and_not_empty_success():
    with TestClient(create_app(Repository())) as client:
        response = client.get('/api/board/greenhouse?board=fail')
        assert response.status_code == 503
        assert 'secret' not in response.text and 'postgresql' not in response.text
        assert response.headers['cache-control'] == 'no-store'


def test_candidate_error_is_422():
    class Missing:
        def load(self, filters, page, *, budget=None): raise ValueError('Candidate unavailable')
    with TestClient(create_app(Missing())) as client:
        assert client.get('/api/board/greenhouse?candidate_id=unknown').status_code == 422


def test_version_mismatch_fails_before_app_creation(monkeypatch):
    monkeypatch.setattr('job_machine.board.app.version', lambda _: '0.1.0')
    with pytest.raises(RuntimeError, match='version'):
        create_app(Repository())


def test_database_timestamps_and_ids_are_serialized():
    from datetime import datetime, timezone
    from uuid import UUID
    class Rows:
        def load(self, filters, page, *, budget=None):
            return GreenhouseSnapshot(candidate_id='alpha', total_rows=1,
                rows=[dict(vacancy_id=UUID(int=1), title='Example', discovered_at=datetime(2026, 10, 15, tzinfo=timezone.utc))])
    with TestClient(create_app(Rows())) as client:
        response = client.get('/api/board/greenhouse')
        assert response.status_code == 200
        assert datetime.fromisoformat(response.json()['table']['rows'][0]['discovered_at']) == datetime(2026, 10, 15, tzinfo=timezone.utc)


def test_snapshot_origin_precedes_completion():
    with TestClient(create_app(Repository())) as client:
        report = client.get('/api/board/greenhouse').json()
        assert report['table']['row_key'] == 'vacancy_id'
        assert report['meta']['context']['candidate_id'] == 'alpha'
        assert report['meta']['snapshot_age_ms'] >= 0
        assert report['meta']['snapshot_at'] <= report['meta']['fetched_at']
        assert report['meta']['read_id']


def test_busy_pipeline_does_not_block_health():
    import asyncio
    from threading import Event
    import httpx
    gate = Event()
    entered = Event()
    class Held(Repository):
        def load(self, filters, page, *, budget=None):
            entered.set()
            gate.wait(5)
            return super().load(filters, page)
    async def run():
        app = create_app(Held())
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
                first = asyncio.create_task(client.get('/api/board/greenhouse'))
                await asyncio.to_thread(entered.wait, 2)
                second = asyncio.create_task(client.get('/api/board/greenhouse'))
                await asyncio.sleep(0)
                try:
                    assert (await client.get('/healthz')).status_code == 200
                    busy = await client.get('/api/board/greenhouse')
                    assert busy.status_code == 503
                    assert busy.headers['retry-after'] == '60'
                finally:
                    gate.set()
                    assert (await first).status_code == 200
                    assert (await second).status_code == 200
    asyncio.run(run())
