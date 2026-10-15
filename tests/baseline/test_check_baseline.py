import importlib.util
from pathlib import Path
from unittest.mock import Mock
import pytest
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]

def test_dotenv_autoload_cannot_restore_live_configuration(tmp_path):
    module = load_runner()
    child = tmp_path / 'checkout'
    child.mkdir()
    (tmp_path / '.env').write_text('BROWSER_WORKER_URL=http://live.invalid\n')
    probe = child / 'probe.py'
    probe.write_text("from dotenv import load_dotenv\nimport os\nload_dotenv()\nassert 'BROWSER_WORKER_URL' not in os.environ\n")
    env = module.build_check_env(os.environ, child)
    result = subprocess.run([sys.executable, str(probe)], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr

def load_runner():
    path = ROOT / 'scripts/check_baseline.py'
    assert path.exists(), 'safe baseline runner is not implemented'
    spec = importlib.util.spec_from_file_location('check_baseline', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

@pytest.mark.parametrize('env', [{'DATABASE_URL': 'postgresql://secret@localhost/job_machine'},
                                  {'SUBMIT_MODE': 'live'}])
def test_rejects_live_configuration(env, tmp_path):
    module = load_runner()
    with pytest.raises(module.UnsafeCheckEnvironment):
        module.build_check_env(env, tmp_path)

def test_rejects_local_dotenv(tmp_path):
    module = load_runner()
    (tmp_path / '.env').write_text('SECRET=hidden')
    with pytest.raises(module.UnsafeCheckEnvironment):
        module.build_check_env({}, tmp_path)

def test_environment_is_isolated_and_path_preserved(tmp_path):
    module = load_runner()
    root = tmp_path / 'Проект с пробелами'
    root.mkdir()
    source = {'PATH': 'system-path', 'API_KEY': 'secret', 'BROWSER_WORKER_URL': 'live'}
    result = module.build_check_env(source, root)
    assert result['SUBMIT_MODE'] == 'disabled'
    assert result['DATABASE_URL'] == module.TEST_DSN
    assert result['PYTHONPATH'] == str(root / 'src')
    assert 'API_KEY' not in result and 'BROWSER_WORKER_URL' not in result
    assert source['API_KEY'] == 'secret'

def test_invalid_environment_never_spawns(monkeypatch, tmp_path):
    module = load_runner()
    spawn = Mock()
    monkeypatch.setattr(module, 'ROOT', tmp_path)
    monkeypatch.setattr(module.os, 'environ', {'SUBMIT_MODE': 'live'})
    monkeypatch.setattr(module.subprocess, 'run', spawn)
    assert module.main(['unit']) == 2
    spawn.assert_not_called()

def test_safe_command_and_exit_code(monkeypatch, tmp_path):
    module = load_runner()
    spawn = Mock(return_value=Mock(returncode=4))
    monkeypatch.setattr(module, 'ROOT', tmp_path)
    monkeypatch.setattr(module.os, 'environ', {})
    monkeypatch.setattr(module.subprocess, 'run', spawn)
    assert module.main(['smoke']) == 4
    args, kw = spawn.call_args
    assert isinstance(args[0], list) and kw['shell'] is False
    assert kw['cwd'] == tmp_path
    assert 'tests/mcp/test_server_registration.py' in args[0]
    base = args[0][args[0].index('--basetemp') + 1]
    assert Path(base).is_relative_to(tmp_path / '.runtime')
