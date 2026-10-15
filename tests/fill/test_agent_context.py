import hashlib
from types import SimpleNamespace

from job_machine.fill import service
from job_machine.package.builder import build_package
from job_machine.package.models import PackageInput, ResumeArtifact, AnswerRecord


def test_context_uses_verified_package_answers_and_rejects_tamper(tmp_path, monkeypatch):
    manifest = build_package(PackageInput(application_id='app1', company='Synthetic',
        role='Tester', destination_url='https://example.com/apply'),
        [AnswerRecord(field='phone',value='555',state='locked'),
         AnswerRecord(field='salary',value='',state='blocked')],
        ResumeArtifact(filename='test.pdf',path='test.pdf',content_hash='abc'))
    path = tmp_path/'manifest.json'
    path.write_text(manifest.model_dump_json(),encoding='utf-8')
    row = {'path':str(path),'content_hash':hashlib.sha256(path.read_bytes()).hexdigest(),
           'payload_hash':manifest.payload_hash,'session_id':'s1'}
    monkeypatch.setattr(service.store,'load_agent_package',lambda *a: row)
    result = service.agent_fill_context(None,'app1','s1')
    assert result['answers'] == [{'field':'phone','value':'555','source':'locked'}]
    assert service.agent_fill_context(None,'app1','old')['error'] == 'stale_session'
    path.write_text('{}',encoding='utf-8')
    assert service.agent_fill_context(None,'app1','s1')['error'] == 'package_unverified'


def test_http_client_receives_context_from_fill_worker(monkeypatch):
    from fastapi.testclient import TestClient
    from job_machine.fill.app import create_app
    from job_machine.mcp.fill_worker_client import FillWorkerClient
    conn = SimpleNamespace(close=lambda: None)
    monkeypatch.setattr(service, 'agent_fill_context', lambda c,a,s: {
        'ok': a == 'app1' and s == 's1', 'answers': [{'field':'phone','value':'555'}]})
    with TestClient(create_app(conn_factory=lambda:conn)) as http:
        worker = FillWorkerClient('http://test', http=http)
        assert worker.agent_context('app1','s1')['answers'][0]['value'] == '555'
