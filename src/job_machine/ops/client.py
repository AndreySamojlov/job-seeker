"""Bounded SSH operations on existing job-machine containers. No compose up/down."""
import json
from pathlib import Path
import re
import shlex
import subprocess
import uuid

SERVICES = ('browser', 'discovery', 'triage', 'resume', 'package', 'fill', 'submit', 'mail')

class TransientTransportError(RuntimeError):
    """Transient connection failure. Mutations must never be retried automatically."""

INSPECT = ('{"Id":{{json .Id}},"Name":{{json .Name}},"Image":{{json .Image}},'
           '"ImageTag":{{json .Config.Image}},"State":{"Running":{{json .State.Running}},'
           '"Status":{{json .State.Status}},"Health":{{with (index .State "Health")}}{{json .Status}}{{else}}null{{end}}},'
           '"Mounts":{{json .Mounts}}}')

def redact(text: str) -> str:
    text = re.sub(r'(?i)(bearer\s+)[^\s"\']+', r'\1[REDACTED]', text)
    text = re.sub(r'(?i)(postgres(?:ql)?://)[^\s@]+@', r'\1[REDACTED]@', text)
    text = re.sub(r'(?i)((?:[\w-]*(?:token|password|secret|api_key))["\']?\s*[:=]\s*["\']?)[^\s,"\']+', r'\1[REDACTED]', text)
    return re.sub(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}', '[EMAIL]', text)

def ssh_transport(command: list[str], *, stdin: str | None = None) -> str:
    args = ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5', 'lab-do', shlex.join(command)]
    # Never share the MCP JSON-RPC input pipe with ssh. Data queries get their own pipe.
    input_options = {'input': stdin} if stdin is not None else {'stdin': subprocess.DEVNULL}
    try:
        result = subprocess.run(args, **input_options, text=True, encoding='utf-8',
                                capture_output=True, timeout=45, shell=False)
    except subprocess.TimeoutExpired as exc:
        raise TransientTransportError('SSH timeout; outcome of a requested service action may be unknown. Inspect status before retry.') from exc
    except OSError:
        raise RuntimeError('SSH process could not be started; check local OpenSSH installation') from None
    if result.returncode:
        error_type = RuntimeError
        if result.returncode == 255 and any(message in result.stderr.lower() for message in
                ('connection timed out', 'connection reset by peer', 'connection refused', 'connection closed by remote host')):
            error_type = TransientTransportError
        raise error_type(f'lab-do operation failed (exit {result.returncode}): {redact(result.stderr[-1000:])}')
    return result.stdout

def container(service: str) -> str:
    if service not in SERVICES:
        raise ValueError('Unknown Job Machine service')
    return f'greenhouse-runtime-job-{service}-1'

class RuntimeClient:
    def __init__(self, transport=ssh_transport):
        self.transport = transport

    def status(self) -> list[dict]:
        output = self.transport(['docker', 'inspect', '--format', INSPECT, *map(container, SERVICES)])
        if output.strip() == '[]':
            return []
        return [json.loads(line) for line in output.splitlines() if line.strip()]

    def logs(self, service: str, lines: int = 40) -> str:
        name = container(service)
        if type(lines) is not int or not 1 <= lines <= 200:
            raise ValueError('lines must be between 1 and 200')
        # Docker logs writes application stderr on stderr; merge inside a fixed sh invocation.
        cmd = ['sh', '-c', 'docker logs --tail "$1" "$2" 2>&1', 'job-logs', str(lines), name]
        return redact(self.transport(cmd))

    def data(self, view: str, limit: int = 20, candidate_id: str | None = None,
             application_id: str | None = None) -> list[dict]:
        from job_machine.ops.remote_data import query
        request = dict(view=view, limit=limit, candidate_id=candidate_id, application_id=application_id)
        query(request)  # validate before SSH
        if application_id:
            request['application_id'] = str(uuid.UUID(application_id))
        script = 'REQUEST = ' + repr(request) + '\n' + Path(__file__).with_name('remote_data.py').read_text(encoding='utf-8')
        result = json.loads(self.transport(['docker', 'exec', '-i', container('package'), 'python', '-'], stdin=script))
        if not isinstance(result, list):
            raise RuntimeError('Runtime query did not return a result list')
        return result

    def health(self, service: str) -> dict:
        name = container(service)
        script = "import json,urllib.request; r=urllib.request.urlopen('http://127.0.0.1:8080/healthz',timeout=5); print(json.dumps({'http_status':r.status,'body':json.loads(r.read())}))"
        return json.loads(self.transport(['docker', 'exec', name, 'python', '-c', script]))

    def service(self, action: str, service: str, expected_image: str, *, execute: bool = False,
                allow_interruption: bool = False) -> dict:
        name = container(service)
        if action not in {'start', 'stop', 'restart'} or not execute or not expected_image.startswith('sha256:'):
            raise ValueError('Explicit execute, allowed action, and expected image ID are required')
        if action in {'stop', 'restart'} and not allow_interruption:
            raise ValueError('Explicit allow_interruption required: may interrupt forms and leave submit outcome unknown')
        before = json.loads(self.transport(['docker', 'inspect', '--format', INSPECT, name]))
        if before['Image'] != expected_image:
            raise RuntimeError('Runtime image changed; inspect and review before retry')
        if not any(m.get('Name') == 'greenhouse-runtime-data' and m.get('Destination') == '/data' for m in before['Mounts']):
            raise RuntimeError('Expected existing data volume is not attached')
        self.transport(['docker', action, before['Id']])
        after = json.loads(self.transport(['docker', 'inspect', '--format', INSPECT, before['Id']]))
        expected_running = action != 'stop'
        if after['Image'] != expected_image or after['State']['Running'] != expected_running:
            raise RuntimeError('Service did not reach the requested state; inspect before retry')
        return {'action': action, 'service': service, 'before': before, 'after': after}
