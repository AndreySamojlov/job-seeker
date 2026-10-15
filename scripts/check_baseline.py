"""Run local checks without inheriting live application configuration."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import uuid
from typing import Mapping

ROOT = Path(__file__).resolve().parents[1]
TEST_DSN = 'postgresql://audit_disabled:audit_disabled@127.0.0.1:1/job_machine_test?connect_timeout=1'

class UnsafeCheckEnvironment(ValueError):
    pass

def build_check_env(source: Mapping[str, str], root: Path) -> dict[str, str]:
    if (root / '.env').exists():
        raise UnsafeCheckEnvironment('Local .env exists; use an isolated checkout for tests.')
    if source.get('DATABASE_URL', TEST_DSN) != TEST_DSN or source.get('SUBMIT_MODE', 'disabled') != 'disabled':
        raise UnsafeCheckEnvironment('Live database/submit configuration is not accepted by the test runner.')
    allowed = {'PATH', 'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PATHEXT', 'TEMP', 'TMP',
               'USERPROFILE', 'LOCALAPPDATA', 'APPDATA'}
    env = {k: v for k, v in source.items() if k.upper() in allowed}
    env.update(DATABASE_URL=TEST_DSN, SUBMIT_MODE='disabled', PYTHONDONTWRITEBYTECODE='1',
               PYTHONPATH=str(root / 'src'), PYTHONIOENCODING='utf-8', PYTHON_DOTENV_DISABLED='1')
    return env

def pytest_args(suite: str) -> list[str]:
    args = [sys.executable, '-m', 'pytest']
    if suite == 'smoke':
        args += ['tests/dashboard/test_app.py', 'tests/dashboard/test_render.py',
                 'tests/mcp/test_server_registration.py', 'tests/ops', 'tests/baseline']
    elif suite != 'unit':
        raise ValueError('Unknown suite')
    return args + ['-m', 'not db and not browser', '-p', 'no:cacheprovider', '-q', '--tb=short']

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('suite', choices=['unit', 'smoke'])
    args = parser.parse_args(argv)
    try:
        env = build_check_env(os.environ, ROOT)
    except UnsafeCheckEnvironment as exc:
        print(str(exc), file=sys.stderr)
        return 2
    scratch = ROOT / '.runtime'
    scratch.mkdir(exist_ok=True)
    command = pytest_args(args.suite) + ['--basetemp', str(scratch / ('pytest-' + uuid.uuid4().hex))]
    return subprocess.run(command, cwd=ROOT, env=env, shell=False).returncode

if __name__ == '__main__':
    raise SystemExit(main())
