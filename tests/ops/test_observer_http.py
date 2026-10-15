import pytest
from fastapi.testclient import TestClient


@pytest.mark.parametrize('failed', ['summary', 'blockers', 'ready', 'observations', 'status'])
def test_partial_failure_does_not_stop_independent_reads(failed):
    from job_machine.ops.dashboard import create_app
    class Source:
        def __init__(self): self.seen = []
        def data(self, view, **kwargs):
            self.seen.append(view)
            if view == failed: raise RuntimeError('password=synthetic')
            return []
        def status(self):
            self.seen.append('status')
            if failed == 'status': raise RuntimeError('offline')
            return []
    source = Source()
    with TestClient(create_app(source)) as client:
        response = client.get('/')
        assert response.status_code == 200
        assert response.headers['X-Job-Machine-Data'] == 'partial'
        assert response.headers['Cache-Control'] == 'no-store'
        assert set(source.seen) == {'summary', 'blockers', 'ready', 'observations', 'status'}
        assert 'synthetic' not in response.text


def test_all_database_reads_failed_still_shows_container_data():
    from job_machine.ops.dashboard import create_app
    class Source:
        def data(self, *args, **kwargs): raise RuntimeError('offline')
        def status(self):
            return [dict(Name='fixture-worker', ImageTag='fixture', State=dict(Status='running', Health='healthy'))]
    with TestClient(create_app(Source())) as client:
        response = client.get('/')
        assert response.status_code == 503
        assert response.headers['X-Job-Machine-Data'] == 'unavailable'
        assert 'fixture-worker' in response.text
        assert 'Блокеров нет' not in response.text
        assert 'Очередь пуста' not in response.text


def test_invalid_summary_is_unavailable_not_a_server_error():
    from job_machine.ops.dashboard import create_app
    class Source:
        def data(self, view, **kwargs): return [{'count': 'invalid'}] if view == 'summary' else []
        def status(self): return []
    with TestClient(create_app(Source())) as client:
        response = client.get('/')
        assert response.status_code == 200
        assert response.headers['X-Job-Machine-Data'] == 'partial'
        assert 'Сводка состояний: сведения недоступны' in response.text


def test_snapshot_expiring_during_status_read_is_not_rendered(monkeypatch):
    import job_machine.ops.dashboard as dashboard
    now = [0.0]
    monkeypatch.setattr(dashboard.time, 'monotonic', lambda: now[0])
    class Source:
        broken = False
        def data(self, view, **kwargs):
            if self.broken: raise RuntimeError('offline')
            return []
        def status(self):
            if self.broken: now[0] += 2
            return []
    source = Source()
    with TestClient(dashboard.create_app(source)) as client:
        assert client.get('/').headers['X-Job-Machine-Data'] == 'live'
        source.broken = True
        now[0] = 299
        response = client.get('/')
        assert response.status_code == 503
        assert response.headers['X-Job-Machine-Data'] == 'unavailable'
        assert 'Блокеров нет' not in response.text
