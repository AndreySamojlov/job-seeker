"""Dashboard reads through the user's existing tunnel-daemon, never a new tunnel."""
import json
from pathlib import Path
from urllib.request import urlopen
from urllib.error import URLError
import psycopg
from psycopg.rows import dict_row
from dotenv import dotenv_values
from job_machine.ops.client import RuntimeClient, TransientTransportError
from job_machine.ops.remote_data import query

def postgres_tunnel_status():
    try:
        with urlopen('http://127.0.0.1:47100/status/postgres', timeout=3) as response:
            return json.load(response)
    except (URLError, TimeoutError, ValueError) as exc:
        raise TransientTransportError('Local tunnel-daemon status unavailable') from None

class TunnelDashboardClient(RuntimeClient):
    def __init__(self, *, config_path=None, connect=psycopg.connect,
                 tunnel_status=postgres_tunnel_status):
        super().__init__()
        self.config_path = config_path or Path.home()/'.claude/tools/tunnel-daemon/.env'
        self.connect = connect
        self.tunnel_status = tunnel_status

    def data(self, view, limit=20, **kwargs):
        if view not in {'summary','blockers','ready','observations'}:
            raise ValueError('Unsupported read-only dashboard view')
        sql, params = query({'view':view, 'limit':limit})
        status = self.tunnel_status()
        if not status.get('desired'):
            raise RuntimeError('PostgreSQL tunnel intentionally stopped; it will not be restarted automatically')
        if status.get('state') != 'healthy':
            raise TransientTransportError('PostgreSQL tunnel is not healthy')
        if status.get('local_port') != 15433 or status.get('remote_port') != 5432:
            raise RuntimeError('Unexpected PostgreSQL tunnel mapping')
        password = dotenv_values(self.config_path, interpolate=False).get('TUNNEL_DAEMON_PG_PASSWORD')
        if not password:
            raise RuntimeError('Authorized tunnel-daemon database credential unavailable')
        try:
            with self.connect(host='127.0.0.1', port=15433, user='admin', password=password,
                              dbname='job_machine', connect_timeout=5, row_factory=dict_row,
                              options='-c default_transaction_read_only=on -c statement_timeout=10000') as conn:
                return conn.execute(sql, params).fetchall()
        except psycopg.OperationalError:
            raise TransientTransportError('Read-only database connection through tunnel-daemon failed') from None
        except psycopg.Error:
            raise RuntimeError('Read-only dashboard database query failed') from None
