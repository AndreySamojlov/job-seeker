import importlib.util
import json
from unittest.mock import Mock
import pytest

def test_ssh_does_not_inherit_mcp_stdin(monkeypatch):
    module = client_module()
    run = Mock(return_value=Mock(returncode=0, stdout='ok'))
    monkeypatch.setattr(module.subprocess, 'run', run)
    assert module.ssh_transport(['true']) == 'ok'
    assert run.call_args.kwargs['stdin'] == module.subprocess.DEVNULL
    module.ssh_transport(['python', '-'], stdin='print(1)')
    assert run.call_args.kwargs['input'] == 'print(1)'
    assert 'stdin' not in run.call_args.kwargs

def client_module():
    assert importlib.util.find_spec('job_machine.ops'), 'lab-do operations adapter is not implemented'
    from job_machine.ops import client
    return client

def test_service_injection_rejected_without_ssh():
    module = client_module()
    transport = Mock()
    ops = module.RuntimeClient(transport=transport)
    with pytest.raises(ValueError):
        ops.logs('browser; rm -rf /', 10)
    transport.assert_not_called()

def test_status_does_not_read_environment():
    module = client_module()
    transport = Mock(return_value='[]')
    assert module.RuntimeClient(transport=transport).status() == []
    command = transport.call_args.args[0]
    assert 'inspect' in command and '.Config.Env' not in ' '.join(command)
    assert 'index .State "Health"' in ' '.join(command), 'containers without healthcheck must be supported'
    assert all('lab-postgres' != arg for arg in command)

def test_query_is_read_only_and_parameters_not_shell_code():
    module = client_module()
    transport = Mock(return_value='[]')
    module.RuntimeClient(transport=transport).data('applications', limit=2, candidate_id="x'; select 1 --")
    command = transport.call_args.args[0]
    script = transport.call_args.kwargs['stdin']
    assert command[-2:] == ['python', '-']
    assert 'default_transaction_read_only=on' in script
    assert "x'; select 1 --" not in ' '.join(command)

def test_unknown_query_and_unbounded_limit_rejected():
    module = client_module()
    transport = Mock()
    ops = module.RuntimeClient(transport=transport)
    with pytest.raises(ValueError): ops.data('drop table application')
    with pytest.raises(ValueError): ops.data('applications', limit=100000)
    transport.assert_not_called()

def test_service_change_requires_image_and_explicit_execute():
    module = client_module()
    transport = Mock()
    ops = module.RuntimeClient(transport=transport)
    with pytest.raises(ValueError): ops.service('restart', 'browser', '', execute=True)
    with pytest.raises(ValueError): ops.service('restart', 'browser', 'sha256:old', execute=False)
    transport.assert_not_called()

def test_changed_image_prevents_service_mutation():
    module = client_module()
    transport = Mock(return_value=json.dumps({'Id':'id', 'Image':'sha256:new', 'State':{'Running':True}, 'Mounts':[]}))
    with pytest.raises(RuntimeError, match='image'):
        module.RuntimeClient(transport=transport).service('restart', 'browser', 'sha256:old', execute=True, allow_interruption=True)
    assert transport.call_count == 1

def test_logs_redact_common_credentials():
    module = client_module()
    transport = Mock(return_value='Authorization: Bearer topsecret\npostgresql://admin:password@db/x\nAPI_KEY=abc\nnormal message')
    result = module.RuntimeClient(transport=transport).logs('submit', 10)
    assert 'topsecret' not in result and 'password' not in result and 'abc' not in result
    assert 'normal message' in result

def test_interruption_requires_explicit_acknowledgement_before_ssh():
    module = client_module()
    current = {'Id':'a'*64,'Image':'sha256:old','State':{'Running':True},
               'Mounts':[{'Name':'greenhouse-runtime-data','Destination':'/data'}]}
    transport = Mock(side_effect=[json.dumps(current), '[{"active":1}]'])
    with pytest.raises(ValueError, match='interruption'):
        module.RuntimeClient(transport=transport).service('stop','browser','sha256:old',execute=True)
    transport.assert_not_called()

def test_lifecycle_preserves_existing_container_identity():
    module = client_module()
    current = {'Id':'a'*64,'Image':'sha256:old','State':{'Running':True},
               'Mounts':[{'Name':'greenhouse-runtime-data','Destination':'/data'}]}
    after = {**current, 'State':{'Running':False}}
    transport = Mock(side_effect=[json.dumps(current),'',json.dumps(after)])
    result = module.RuntimeClient(transport=transport).service('stop','mail','sha256:old',execute=True,allow_interruption=True)
    assert transport.call_args_list[1].args[0] == ['docker','stop','a'*64]
    assert result['after']['Image'] == result['before']['Image']
