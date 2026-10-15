import os

from dotenv import load_dotenv
import psycopg

load_dotenv()


def get_dsn(env=None):
    """Return the Postgres DSN from the environment.

    env: optional mapping for testing; defaults to os.environ.
    """
    source = env if env is not None else os.environ
    dsn = source.get("DATABASE_URL")
    if not dsn:
        raise RuntimeError("DATABASE_URL is not set (see .env.example)")
    return dsn


def connect(dsn=None):
    """Open a psycopg connection using the given DSN or the env DSN."""
    return psycopg.connect(dsn or get_dsn())
