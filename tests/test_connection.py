import pytest
from job_machine.db.connection import get_dsn


def test_get_dsn_from_explicit_env():
    env = {"DATABASE_URL": "postgresql://u:p@h:5432/job_machine"}
    assert get_dsn(env) == "postgresql://u:p@h:5432/job_machine"


def test_get_dsn_missing_raises():
    with pytest.raises(RuntimeError):
        get_dsn({})
