"""[SAFETY] MCP-путь к рубильнику подачи (runtime_control). До этого среза
set_submit_enabled не вызывался нигде вне тестов — рубильник фактически нечем
было включить после деплоя (миграция 0024 сеет его выключенным, fail-closed)."""
import pytest

from job_machine.db import migrate
from job_machine.mcp import tools


def _apply(conn):
    for m in migrate.pending(migrate.discover_migrations("db/migrations"),
                             migrate.applied_migrations(conn)):
        migrate.apply_migration(conn, m)


@pytest.mark.db
def test_get_submit_control_reflects_migration_seed(db_schema):
    conn, _ = db_schema
    _apply(conn)
    status = tools.get_submit_control(conn)
    assert status["enabled"] is False
    assert status["updated_by"] == "migration"


@pytest.mark.db
def test_set_submit_control_enables_and_records_actor(db_schema):
    conn, _ = db_schema
    _apply(conn)
    result = tools.set_submit_control(conn, True, actor="andrey-s")
    assert result["ok"] is True
    assert result["enabled"] is True
    status = tools.get_submit_control(conn)
    assert status["enabled"] is True
    assert status["updated_by"] == "andrey-s"


@pytest.mark.db
def test_set_submit_control_disables(db_schema):
    conn, _ = db_schema
    _apply(conn)
    tools.set_submit_control(conn, True, actor="andrey-s")
    result = tools.set_submit_control(conn, False, actor="andrey-s")
    assert result["ok"] is True
    assert result["enabled"] is False
    assert tools.get_submit_control(conn)["enabled"] is False


@pytest.mark.db
def test_set_submit_control_requires_actor(db_schema):
    conn, _ = db_schema
    _apply(conn)
    with pytest.raises(ValueError, match="runtime_control_actor_required"):
        tools.set_submit_control(conn, True, actor="")
