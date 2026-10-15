from contextlib import contextmanager

import pytest

from job_machine.board.config import local_read_connection


@pytest.mark.parametrize('status', [dict(desired=False, state='healthy', local_port=15433, remote_port=5432),
    dict(desired=True, state='stopped', local_port=15433, remote_port=5432),
    dict(desired=True, state='healthy', local_port=25439, remote_port=5432),
    dict(desired=True, state='healthy', local_port=15433, remote_port=5433)])
def test_stopped_or_mismapped_tunnel_never_reads_credential_or_connects(monkeypatch, status):
    monkeypatch.setattr('job_machine.board.config.postgres_tunnel_status', lambda: status)
    def forbidden(*args, **kwargs):
        pytest.fail('Must reject mapping before credential read or connection')
    monkeypatch.setattr('job_machine.board.config.dotenv_values', forbidden)
    monkeypatch.setattr('job_machine.board.config.psycopg.connect', forbidden)
    with pytest.raises(RuntimeError):
        with local_read_connection(): pass


def test_authorized_connection_is_read_only_without_exporting_secret(monkeypatch):
    monkeypatch.setattr('job_machine.board.config.postgres_tunnel_status', lambda: dict(desired=True, state='healthy', local_port=15433, remote_port=5432))
    monkeypatch.setattr('job_machine.board.config.dotenv_values', lambda *a, **k: {'TUNNEL_DAEMON_PG_PASSWORD': 'synthetic-only'})
    @contextmanager
    def connection(**kwargs):
        assert kwargs['host'] == '127.0.0.1' and kwargs['port'] == 15433
        assert kwargs['dbname'] == 'job_machine'
        assert 'default_transaction_read_only=on' in kwargs['options']
        assert 'statement_timeout=10000' in kwargs['options']
        yield object()
    monkeypatch.setattr('job_machine.board.config.psycopg.connect', connection)
    with local_read_connection() as conn:
        assert conn is not None
