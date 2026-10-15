from importlib.util import find_spec
from fastapi.testclient import TestClient
import pytest

def test_outage_uses_explicit_bounded_stale_snapshot_then_recovers(monkeypatch):
    import job_machine.ops.dashboard as dashboard
    now=[100.0]
    monkeypatch.setattr(dashboard.time,'monotonic',lambda:now[0])
    class Source:
        broken=False
        def data(self,view,**kwargs):
            if self.broken: raise RuntimeError('source down')
            return []
        def status(self): return []
    source=Source()
    with TestClient(dashboard.create_app(source)) as client:
        assert client.get('/').headers['X-Job-Machine-Data']=='live'
        source.broken=True
        response=client.get('/')
        assert response.status_code==200
        assert response.headers['X-Job-Machine-Data']=='stale'
        assert 'Последний успешный снимок' in response.text
        now[0]=401.0
        assert client.get('/').status_code==503
        source.broken=False
        assert client.get('/').headers['X-Job-Machine-Data']=='live'

def test_container_status_failure_keeps_live_application_data(caplog):
    from job_machine.ops.dashboard import create_app
    class Partial:
        def data(self, view, **kwargs):
            return [{'entity':'application','state':'submitted','count':15}] if view == 'summary' else []
        def status(self): raise RuntimeError('SSH unavailable')
    with TestClient(create_app(Partial())) as client:
        response = client.get('/')
        assert response.status_code == 200
        assert 'submitted' in response.text.lower()
        assert 'Статус контейнеров недоступен' in response.text
        assert 'SSH unavailable' in caplog.text

@pytest.mark.parametrize('failures,expected', [(1,'live'),(2,'partial')])
def test_transient_connection_failure_has_one_read_retry(failures, expected):
    from job_machine.ops.client import TransientTransportError
    from job_machine.ops.dashboard import create_app
    class Flaky:
        calls = 0
        def data(self, view, **kwargs):
            if view == 'summary':
                self.calls += 1
                if self.calls <= failures:
                    raise TransientTransportError('connection timed out')
            return []
        def status(self): return []
    runtime = Flaky()
    with TestClient(create_app(runtime)) as client:
        response = client.get('/')
        assert response.status_code == 200
        assert response.headers['X-Job-Machine-Data'] == expected
    assert runtime.calls == 2

def test_live_dashboard_adapter_is_read_only_and_keeps_unknowns():
    assert find_spec('job_machine.ops.dashboard'), 'live dashboard adapter missing'
    from job_machine.ops.dashboard import create_app
    class Fake:
        def data(self, view, **kwargs):
            if view == 'summary':
                return [{'entity':'application','state':'submit_unknown','count':23}]
            if view == 'blockers': return []
            if view == 'ready': return [{'candidate_id':'candidate','company':'<script>', 'role':'QA','url':'https://example.test'}]
            return []
        def status(self): return []
    with TestClient(create_app(Fake())) as client:
        response = client.get('/')
        assert response.status_code == 200
        assert 'submit_unknown: 23' in response.text
        assert '&lt;script&gt;' in response.text
        assert 'lab-do' in response.text
        assert client.post('/').status_code == 405

def test_failure_is_visible_not_empty_funnel():
    assert find_spec('job_machine.ops.dashboard'), 'live dashboard adapter missing'
    from job_machine.ops.dashboard import create_app
    class Unavailable:
        def data(self, *args, **kwargs): raise RuntimeError('remote unavailable')
        def status(self): raise RuntimeError('remote unavailable')
    with TestClient(create_app(Unavailable())) as client:
        assert client.get('/').status_code == 503

def test_failure_logs_stage_without_credentials_and_next_request_recovers(caplog):
    from job_machine.ops.dashboard import create_app
    class Flaky:
        failed = False
        def data(self, view, **kwargs):
            if view == 'blockers' and not self.failed:
                self.failed = True
                raise RuntimeError('SSH failure password=private-value')
            return []
        def status(self): return []
    with TestClient(create_app(Flaky())) as client:
        response = client.get('/')
        assert response.status_code == 200
        assert response.headers['X-Job-Machine-Data'] == 'partial'
        assert 'blockers' in caplog.text
        assert 'SSH failure' in caplog.text
        assert 'private-value' not in caplog.text + response.text
        recovered = client.get('/')
        assert recovered.status_code == 200
        assert recovered.headers['X-Job-Machine-Data'] == 'live'
