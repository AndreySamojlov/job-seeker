"""Persistent RWR-only circuit breaker; the submit control remains separate."""


def read_control(conn) -> dict:
    row = conn.execute(
        "select enabled,updated_at,updated_by from remote_work_readiness_control where control_id='global'"
    ).fetchone()
    if row is None:
        return {"enabled": False, "updated_at": None, "updated_by": None}
    enabled, updated_at, updated_by = row
    return {
        "enabled": bool(enabled),
        "updated_at": updated_at.isoformat() if updated_at else None,
        "updated_by": updated_by,
    }


def is_enabled(conn) -> bool:
    return read_control(conn)["enabled"]


def set_enabled(conn, enabled: bool, *, actor: str) -> bool:
    if not isinstance(enabled, bool):
        raise ValueError("invalid_rwr_enabled")
    if not isinstance(actor, str) or not actor.strip() or len(actor.strip()) > 120:
        raise ValueError("rwr_control_actor_required")
    row = conn.execute(
        """insert into remote_work_readiness_control(control_id,enabled,updated_by)
           values ('global',%s,%s)
           on conflict (control_id) do update
           set enabled=excluded.enabled,updated_at=now(),updated_by=excluded.updated_by
           where remote_work_readiness_control.enabled is distinct from excluded.enabled
           returning enabled""",
        (enabled, actor.strip()),
    ).fetchone()
    return bool(row[0]) if row is not None else is_enabled(conn)
