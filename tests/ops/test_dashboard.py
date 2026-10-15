from importlib.util import find_spec
from fastapi.testclient import TestClient

def test_live_dashboard_adapter_is_read_only_and_keeps_unknowns():
    assert find_spec('job_machine.ops.dashboard'), 'live dashboard adapter missing'
    from job_machine.ops.dashboard import create_app
    class Fake:
        def data(self, view, **kwargs):
            if view == 'summary':
                return [{'entity':'application','state':'submit_unknown','count':23}]
            if view == 'blockers': return []
            if view == 'ready': return [{'candidate_id':'candidate','company':'<script>', 'role':'QA','url':'https://example.test'}]
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
    with TestClient(create_app(Unavailable())) as client:
        assert client.get('/').status_code == 503
