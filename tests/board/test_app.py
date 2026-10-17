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


def test_refresh_is_explicitly_enabled_on_installed_engine():
    with TestClient(create_app(Repository())) as client:
        assert '"interval_ms": 60000' in client.get('/').text
        assert client.get('/cockpit-assets/board-refresh.js').status_code == 200


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


def test_builder_value_error_is_not_candidate_error(monkeypatch):
    def broken(*args): raise ValueError('synthetic builder defect')
    monkeypatch.setattr('job_machine.board.app.build_greenhouse_report', broken)
    with TestClient(create_app(Repository())) as client:
        response = client.get('/api/board/greenhouse')
        assert response.status_code == 500
        assert response.json()['code'] == 'invalid_report'
        assert 'candidate_unavailable' not in response.text
        assert 'synthetic' not in response.text


def test_column_filters_cover_whole_report_and_context():
    with TestClient(create_app(Repository())) as client:
        response = client.get('/api/board/greenhouse', params={'column_filters': '{"company":{"q":"Acme"}}'})
        assert response.status_code == 200
        p = response.json()
        assert p['table']['filters'] == {'company': {'q': 'Acme'}}
        assert p['table']['filter_param'] == 'column_filters'
        assert p['meta']['context']['column_filters'] == '{"company":{"q":"Acme"}}'
        readiness = next(c for c in p['table']['columns'] if c['key'] == 'remote_work_readiness')
        assert readiness['filter'] == 'range'
        assert readiness['sortable'] is True
        assert all(c['filter'] in ('text', 'range') for c in p['table']['columns'] if c is not readiness)


def test_readiness_filter_and_sort_are_part_of_board_contract():
    with TestClient(create_app(Repository())) as client:
        response = client.get('/api/board/greenhouse')
        assert response.status_code == 200
        columns = response.json()['table']['columns']
        readiness = next(c for c in columns if c['key'] == 'remote_work_readiness')
        assert readiness['filter'] == 'range'
        assert readiness['sortable'] is True
        accepted_filter = client.get('/api/board/greenhouse', params={
            'column_filters': '{"remote_work_readiness":{"min":0}}',
        })
        assert accepted_filter.status_code == 200
        assert accepted_filter.json()['table']['filters'] == {'remote_work_readiness': {'min': 0}}
        sorted_readiness = client.get('/api/board/greenhouse', params={'sort_key': 'remote_work_readiness'})
        assert sorted_readiness.status_code == 200
        assert sorted_readiness.json()['meta']['context']['sort_key'] == 'remote_work_readiness'


def test_synthetic_fixture_filters_the_complete_selection():
    from tests.board.fixture_app import create_app as fixture_app
    with TestClient(fixture_app()) as client:
        p = client.get('/api/board/greenhouse', params={'column_filters': '{"title":{"q":"vacancy 199"}}'}).json()
        assert p['table']['total_rows'] == 1
        assert len(p['table']['rows']) == 1
        assert p['table']['rows'][0]['title'] == 'Synthetic vacancy 199'


def test_synthetic_fixture_returns_complete_snapshot_for_client_pagination():
    from tests.board.fixture_app import create_app as fixture_app
    with TestClient(fixture_app()) as client:
        first = client.get('/api/board/greenhouse', params={
            'page': 0, 'sort_key': 'title', 'sort_direction': 'asc'}).json()
        second = client.get('/api/board/greenhouse', params={
            'page': 1, 'sort_key': 'title', 'sort_direction': 'asc'}).json()
    assert first['table']['total_rows'] == 201
    assert first['table']['page'] == 0 and len(first['table']['rows']) == 201
    assert second['table']['page'] == 1 and len(second['table']['rows']) == 201
    assert first['table']['client_sort'] is True
    assert {'fit_score', 'remote_work_readiness'} <= set(first['table']['rows'][0])


def test_response_size_limit_returns_unavailable_without_partial_rows(monkeypatch):
    from datetime import datetime, timezone
    monkeypatch.setattr('job_machine.board.app.MAX_RESPONSE_BYTES', 1, raising=False)
    class Large(Repository):
        def load(self, filters, page, *, budget=None):
            return GreenhouseSnapshot(candidate_id='alpha', total_rows=1, rows=[dict(
                vacancy_id='v1', title='Synthetic', url='https://example.test/v1',
                discovered_at=datetime(2026, 10, 15, tzinfo=timezone.utc), fit_score=0,
                remote_work_readiness=None)])
    with TestClient(create_app(Large())) as client:
        response = client.get('/api/board/greenhouse')
    assert response.status_code == 503
    assert response.json()['state'] == 'unavailable'
    assert response.json()['code'] == 'snapshot_too_large'
    assert 'rows' not in response.json()
    assert response.headers['cache-control'] == 'no-store'


def test_repository_snapshot_limit_is_not_misreported_as_candidate_error():
    from job_machine.board.read_budget import SnapshotTooLarge
    class Oversized(Repository):
        def load(self, filters, page, *, budget=None):
            raise SnapshotTooLarge()
    with TestClient(create_app(Oversized())) as client:
        response = client.get('/api/board/greenhouse')
    assert response.status_code == 503
    assert response.json()['code'] == 'snapshot_too_large'
    assert response.json()['state'] == 'unavailable'


def test_snapshot_deadline_is_explicit_unavailable(monkeypatch):
    from job_machine.board.read_budget import ReadBudget, ReadDeadline
    def deadline(self):
        raise ReadDeadline('synthetic timeout')
    monkeypatch.setattr(ReadBudget, 'check_response_deadline', deadline)
    with TestClient(create_app(Repository())) as client:
        response = client.get('/api/board/greenhouse')
    assert response.status_code == 503
    assert response.json()['code'] == 'snapshot_timeout'
    assert response.json()['state'] == 'unavailable'
