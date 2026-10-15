"""[SAFETY] Долговечный рубильник сабмита. Отсутствие строки = выключено."""


def is_submit_enabled(conn, *, for_update: bool = False,
                      for_share: bool = False) -> bool:
    """Прочитать разрешение на сабмит. Fail-closed: нет строки — нет разрешения.

    for_share берётся при claim, чтобы административное выключение не могло
    проскочить между проверкой и резервированием approval.
    """
    if for_update and for_share:
        raise ValueError("conflicting_runtime_control_locks")
    lock = " for update" if for_update else " for share" if for_share else ""
    with conn.cursor() as cur:
        cur.execute(
            f"select enabled from runtime_control where control_id='submit'{lock}")
        row = cur.fetchone()
    return bool(row[0]) if row is not None else False


def set_submit_enabled(conn, enabled: bool, actor: str) -> bool:
    """Переключить рубильник. Авторизация вызывающего — не здесь, а на MCP-слое."""
    if not actor or not actor.strip():
        raise ValueError("runtime_control_actor_required")
    with conn.cursor() as cur:
        cur.execute(
            "update runtime_control set enabled=%s, updated_at=now(), "
            "updated_by=%s where control_id='submit' returning control_id",
            (enabled, actor.strip()))
        return cur.fetchone() is not None


def read_submit_control(conn) -> dict:
    """Полное состояние рубильника (для показа владельцу): enabled + кто/когда менял.

    Отсутствие строки — fail-closed выключено без метаданных (не должно случаться
    после миграции 0024, но не должно и падать, если кто-то удалил строку вручную).
    """
    with conn.cursor() as cur:
        cur.execute(
            "select enabled, updated_at, updated_by from runtime_control "
            "where control_id='submit'")
        row = cur.fetchone()
    if row is None:
        return {"enabled": False, "updated_at": None, "updated_by": None}
    enabled, updated_at, updated_by = row
    return {
        "enabled": bool(enabled),
        "updated_at": updated_at.isoformat() if updated_at else None,
        "updated_by": updated_by,
    }
