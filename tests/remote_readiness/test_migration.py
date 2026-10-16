"""Executable 0039 constraints; no external or real vacancy inputs."""
from uuid import uuid4

import psycopg
import pytest

from tests.remote_readiness.test_store_db import readiness_db, queued

pytestmark = pytest.mark.db


@pytest.mark.parametrize("assignment", [
    "payload='{}'::jsonb", "payload_hash=repeat('0',64)", "model='other'",
    "rubric_version='other'", "vacancy_id=gen_random_uuid()", "created_at=now()+interval '1 day'",
])
def test_snapshot_identity_cannot_change(readiness_db, assignment):
    conn, _, _ = queued(readiness_db)
    with pytest.raises(psycopg.Error), conn.transaction():
        conn.execute("update remote_work_readiness_job set " + assignment)


@pytest.mark.parametrize("assignment", [
    "status='invalid'", "status='processing'", "lease_token=gen_random_uuid()",
    "lease_until=now()", "status='retry_wait'", "attempts=-1", "value=0.4",
    "completed_at=now()", "last_error_code='raw text'",
    "status='completed',completed_at=now()",
    "status='completed',completed_at=now(),value='NaN'::float8",
    "status='completed',completed_at=now(),value='Infinity'::float8",
    "status='completed',completed_at=now(),value=-0.1",
    "status='completed',completed_at=now(),value=1.1",
])
def test_state_and_result_constraints(readiness_db, assignment):
    conn, _, _ = queued(readiness_db)
    with pytest.raises(psycopg.errors.CheckViolation), conn.transaction():
        conn.execute("update remote_work_readiness_job set " + assignment)


def test_one_row_per_vacancy_and_fk(readiness_db):
    conn, _, value = queued(readiness_db)
    statement = "insert into remote_work_readiness_job(vacancy_id,payload,payload_hash,model,rubric_version) values (%s,'{}',repeat('a',64),'jev-1.13.0','rwr-1')"
    with pytest.raises(psycopg.errors.UniqueViolation), conn.transaction():
        conn.execute(statement, (value.vacancy_id,))
    with pytest.raises(psycopg.errors.ForeignKeyViolation), conn.transaction():
        conn.execute(statement, (uuid4(),))


@pytest.mark.parametrize("column", ["model", "rubric_version"])
@pytest.mark.parametrize("value", [None, ""])
def test_snapshot_requires_nonempty_versions(readiness_db, column, value):
    conn, _, input = readiness_db
    statement = "insert into remote_work_readiness_job(vacancy_id,payload,payload_hash,model,rubric_version) values (%s,'{}',repeat('a',64),%s,%s)"
    model, rubric = (value, "rwr-1") if column == "model" else ("jev-1.13.0", value)
    with pytest.raises(psycopg.IntegrityError), conn.transaction():
        conn.execute(statement, (input.vacancy_id, model, rubric))


def test_even_incomplete_snapshot_cannot_be_deleted(readiness_db):
    conn, _, _ = queued(readiness_db)
    with pytest.raises(psycopg.errors.CheckViolation), conn.transaction():
        conn.execute("delete from remote_work_readiness_job")
