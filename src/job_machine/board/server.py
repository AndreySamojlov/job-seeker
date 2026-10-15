"""Server deployment: dedicated read role, file secret, no laptop daemon credential."""
from contextlib import contextmanager
from math import floor

import psycopg
from psycopg.rows import dict_row

from job_machine.board.app import create_app as board_app
from job_machine.board.config import GreenhouseRepository
from job_machine.board.read_budget import ReadBudget, ReadDeadline


@contextmanager
def server_read_connection(*, budget=None):
    budget = budget or ReadBudget()
    timeout = floor(budget.timeout_seconds(5))
    if timeout < 2:
        raise ReadDeadline('Insufficient connection budget')
    with psycopg.connect(host='lab-postgres', port=5432, dbname='job_machine',
                         user='job_board_reader', passfile='/run/secrets/board.pgpass',
                         connect_timeout=timeout, row_factory=dict_row,
                         options=f'-c default_transaction_read_only=on -c statement_timeout={budget.statement_timeout_ms()}') as conn:
        yield conn


def create_app():
    return board_app(GreenhouseRepository(connection=server_read_connection))
