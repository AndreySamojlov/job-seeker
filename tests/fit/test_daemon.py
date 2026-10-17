from datetime import datetime, timezone
import importlib
from threading import Event


def test_polling_continues_after_idle_retry_and_redacts_exceptions(tmp_path):
    assert importlib.util.find_spec('job_machine.fit.daemon'), 'daemon missing'
    from job_machine.fit.daemon import run
    stop = Event()
    calls = []
    output = []
    def prepare(*a, **kw):
        calls.append('prepare')
        if len(calls) == 5:
            raise RuntimeError('secret provider text')
        return 'idle'
    def fit(*a, **kw):
        calls.append('fit')
        return 'retry_wait'
    def wait(seconds):
        assert seconds > 0
        if len(calls) >= 6: stop.set()
    run(lambda: None, client=None, api_key='synthetic', stop=stop,
        clock=lambda: datetime.now(timezone.utc), prepare_once=prepare, fit_once=fit,
        wait=wait, emit=output.append, health_path=tmp_path/'health')
    assert calls == ['prepare', 'fit'] * 3
    assert len(output) == 3
    assert 'secret' not in str(output)
    assert output[-1]['preparation'] == 'operation_failed'
    assert (tmp_path/'health').exists()


def test_health_cli_uses_no_secret_or_database(monkeypatch, capsys):
    from job_machine.fit import __main__ as cli, daemon
    monkeypatch.setattr(daemon, 'healthy', lambda: True)
    assert cli.main(['health']) == 0
    assert 'healthy' in capsys.readouterr().out


def test_health_expires_and_rejects_invalid_data(tmp_path):
    from job_machine.fit.daemon import healthy
    path = tmp_path/'health'
    now = datetime(2030, 1, 1, tzinfo=timezone.utc)
    path.write_text(str(now.timestamp()))
    assert healthy(path, now=now)
    assert not healthy(path, now=datetime(2030, 1, 2, tzinfo=timezone.utc))
    path.write_text('provider secret')
    assert not healthy(path, now=now)


def test_daemon_emits_numeric_bounded_status_counts(tmp_path):
    from job_machine.fit.daemon import run
    stop = Event()
    output = []
    def finish(seconds): stop.set()
    run(lambda: None, client=None, api_key='synthetic', stop=stop,
        clock=lambda: datetime.now(timezone.utc),
        prepare_once=lambda *a, **kw: 'idle', fit_once=lambda *a, **kw: 'quota_exhausted',
        wait=finish, emit=output.append, health_path=tmp_path/'health')
    assert output[0]['counts'] == {'preparation': {'idle': 1}, 'fit': {'quota_exhausted': 1}}
