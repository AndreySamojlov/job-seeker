"""Local S1 connection reuses the authorized daemon; never starts tunnels."""
from contextlib import contextmanager
from pathlib import Path
import json
from urllib.request import urlopen
from math import floor
from job_machine.board.read_budget import ReadBudget, ReadDeadline

from dotenv import dotenv_values
import psycopg
from psycopg.rows import dict_row

from job_machine.board.repository import load_greenhouse_snapshot
from job_machine.ops.tunnel_dashboard import postgres_tunnel_status


@contextmanager
def local_read_connection(*, budget=None):
    if budget is None:
        status = postgres_tunnel_status()
    else:
        with urlopen('http://127.0.0.1:47100/status/postgres', timeout=budget.timeout_seconds(3)) as response:
            status = json.load(response)
    if not status.get('desired') or status.get('state') != 'healthy':
        raise RuntimeError('Authorized PostgreSQL tunnel unavailable')
    if status.get('local_port') != 15433 or status.get('remote_port') != 5432:
        raise RuntimeError('Unexpected PostgreSQL tunnel mapping')
    config = Path.home() / '.claude/tools/tunnel-daemon/.env'
    password = dotenv_values(config, interpolate=False).get('TUNNEL_DAEMON_PG_PASSWORD')
    if not password:
        raise RuntimeError('Authorized read-only credential unavailable')
    connect_timeout = 5 if budget is None else floor(budget.timeout_seconds(5))
    if connect_timeout < 2:
        # libpq's minimum effective connect timeout is two seconds.
        raise ReadDeadline('Insufficient connection budget')
    statement_ms = 10000 if budget is None else budget.statement_timeout_ms()
    with psycopg.connect(host='127.0.0.1', port=15433, user='admin', password=password,
                          dbname='job_machine', connect_timeout=connect_timeout, row_factory=dict_row,
                          options=f'-c default_transaction_read_only=on -c statement_timeout={statement_ms}') as conn:
        yield conn


class GreenhouseRepository:
    def __init__(self, connection=local_read_connection):
        self.connection = connection

    def load(self, filters, page, *, budget=None):
        with self.connection(**({"budget": budget} if budget is not None else {})) as conn:
            return load_greenhouse_snapshot(conn, filters, page, budget=budget)
