"""Persistent RWR control tests; run only through scripts/check_schema.py db."""
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from tests.conftest import apply_migrations

pytestmark = pytest.mark.db


@pytest.fixture
def rwr_control_db(db_schema):
    conn, _ = db_schema
    apply_migrations(conn)
    return conn


def test_control_defaults_disabled_and_enable_disable_are_idempotent(rwr_control_db):
    from job_machine.remote_readiness import control_store
    conn = rwr_control_db
    assert control_store.is_enabled(conn) is False
    assert control_store.set_enabled(conn, True, actor="test-operator") is True
    assert control_store.set_enabled(conn, True, actor="test-operator") is True
    assert control_store.is_enabled(conn) is True
    assert control_store.set_enabled(conn, False, actor="test-operator") is False
    assert control_store.set_enabled(conn, False, actor="test-operator") is False
    assert control_store.is_enabled(conn) is False


def test_disable_preserves_pending_intake_and_completed_snapshot(rwr_control_db):
    from job_machine.remote_readiness import control_store
    conn = rwr_control_db
    intake_id, completed_id = uuid4(), uuid4()
    conn.execute("insert into vacancy(vacancy_id,work_mode,vacancy_status) values (%s,'remote','verified'),(%s,'hybrid','verified')",
                 (intake_id, completed_id))
    conn.execute("insert into remote_work_readiness_intake(vacancy_id) values (%s)", (intake_id,))
    conn.execute(
        """insert into remote_work_readiness_job(vacancy_id,status,payload,payload_hash,model,rubric_version,value,completed_at)
           values (%s,'completed','{}',repeat('a',64),'jev-1.13.0','rwr-1',0.314159,now())""",
        (completed_id,),
    )
    conn.commit()
    before_intake = conn.execute("select status,attempts from remote_work_readiness_intake where vacancy_id=%s", (intake_id,)).fetchone()
    before_result = conn.execute("select status,value,payload_hash,model,rubric_version from remote_work_readiness_job where vacancy_id=%s", (completed_id,)).fetchone()
    assert control_store.set_enabled(conn, False, actor="test-operator") is False
    conn.commit()
    assert conn.execute("select status,attempts from remote_work_readiness_intake where vacancy_id=%s", (intake_id,)).fetchone() == before_intake
    assert conn.execute("select status,value,payload_hash,model,rubric_version from remote_work_readiness_job where vacancy_id=%s", (completed_id,)).fetchone() == before_result


def test_rearm_changes_only_explicit_blocked_incomplete_rows(rwr_control_db):
    from job_machine.remote_readiness import intake_store, store
    from job_machine.remote_readiness.control_store import set_enabled
    conn = rwr_control_db
    blocked_intake, pending_intake, blocked_jev, completed_jev = [uuid4() for _ in range(4)]
    conn.execute("insert into vacancy(vacancy_id) values (%s),(%s),(%s),(%s)",
                 (blocked_intake, pending_intake, blocked_jev, completed_jev))
    conn.execute("insert into remote_work_readiness_intake(vacancy_id,status,last_error_code) values (%s,'blocked','no_content'),(%s,'pending',null)",
                 (blocked_intake, pending_intake))
    conn.execute("""insert into remote_work_readiness_job(vacancy_id,status,payload,payload_hash,model,rubric_version,last_error_code)
                   values (%s,'blocked','{}',repeat('b',64),'jev-1.13.0','rwr-1','invalid_response')""", (blocked_jev,))
    conn.execute("""insert into remote_work_readiness_job(vacancy_id,status,payload,payload_hash,model,rubric_version,value,completed_at)
                   values (%s,'completed','{}',repeat('c',64),'jev-1.13.0','rwr-1',0.8,now())""", (completed_jev,))
    conn.commit()
    now = datetime(2030, 1, 1, tzinfo=timezone.utc)
    assert intake_store.rearm_blocked(conn, blocked_intake, now=now) is True
    assert intake_store.rearm_blocked(conn, pending_intake, now=now) is False
    assert store.rearm_blocked(conn, blocked_jev, now=now) is True
    assert store.rearm_blocked(conn, completed_jev, now=now) is False
    conn.commit()
    assert conn.execute("select status from remote_work_readiness_job where vacancy_id=%s", (completed_jev,)).fetchone() == ("completed",)
