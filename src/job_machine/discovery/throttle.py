"""Межпроходный троттлинг для rate-limited источников дискавери (Remotive, Jobicy).

Хранит давность последнего фетча по source_key в таблице source_fetch_state
(миграция 0017). Вызывающий код (discovery/service.py) должен пропускать
источник без ошибки, если should_skip_fetch вернул True — не блокируя
остальные источники в общем прогоне.
"""

from datetime import datetime, timezone


def should_skip_fetch(conn, source_key: str, min_interval_seconds: int) -> bool:
    """True, если с последнего успешного фетча source_key прошло меньше
    min_interval_seconds — вызывающий код должен пропустить проход без ошибки
    (не блокируя остальные источники в общем прогоне)."""
    if min_interval_seconds <= 0:
        return False
    with conn.cursor() as cur:
        cur.execute(
            "select last_fetched_at from source_fetch_state where source_key = %s",
            (source_key,),
        )
        row = cur.fetchone()
    if row is None or row[0] is None:
        return False
    elapsed = (datetime.now(timezone.utc) - row[0]).total_seconds()
    return elapsed < min_interval_seconds


def record_fetch(conn, source_key: str, status: str = "ok") -> None:
    """Зафиксировать проход source_key (успешный или нет) — upsert по source_key."""
    with conn.cursor() as cur:
        cur.execute(
            "insert into source_fetch_state (source_key, last_fetched_at, last_status) "
            "values (%s, now(), %s) "
            "on conflict (source_key) do update set "
            "last_fetched_at = now(), last_status = excluded.last_status",
            (source_key, status),
        )
    conn.commit()
