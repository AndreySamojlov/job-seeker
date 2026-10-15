from contextlib import contextmanager


def test_server_import_does_not_require_laptop_ops():
    import subprocess
    import sys
    result = subprocess.run([sys.executable, '-c',
        "import job_machine.board.server; import sys; assert 'job_machine.ops.tunnel_dashboard' not in sys.modules"],
        capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_server_uses_dedicated_read_role_and_secret_file(monkeypatch):
    from job_machine.board.server import server_read_connection
    from job_machine.board.read_budget import ReadBudget
    @contextmanager
    def connect(**kwargs):
        assert kwargs['host'] == 'lab-postgres'
        assert kwargs['user'] == 'job_board_reader'
        assert kwargs['dbname'] == 'job_machine'
        assert kwargs['passfile'] == '/run/secrets/board.pgpass'
        assert 'password' not in kwargs
        assert 'default_transaction_read_only=on' in kwargs['options']
        assert 2 <= kwargs['connect_timeout'] <= 5
        yield 'connection'
    monkeypatch.setattr('job_machine.board.server.psycopg.connect', connect)
    with server_read_connection(budget=ReadBudget()) as conn:
        assert conn == 'connection'
