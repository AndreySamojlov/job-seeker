"""Staging-хранилище лидов из Telegram-каналов (telegram_lead, миграция 0018)."""
import json

from job_machine.discovery.store import load_profile_role_patterns


def upsert_lead(conn, msg) -> bool:
    """Insert нового лида; on conflict (channel, message_id) — no-op.
    Возвращает True при реальной вставке."""
    with conn.cursor() as cur:
        cur.execute(
            "insert into telegram_lead (channel, message_id, permalink, posted_at, raw_text) "
            "values (%s, %s, %s, %s, %s) "
            "on conflict (channel, message_id) do nothing returning lead_id",
            (msg.channel, msg.message_id, msg.permalink, msg.posted_at, msg.text),
        )
        row = cur.fetchone()
    return row is not None


def apply_keyword_match(conn) -> int:
    """Проставить keyword_match=true лидам, чей raw_text матчит объединение
    ролей активных кандидатов (переиспользует discovery.store паттерны). Non-
    destructive — флаг для сортировки внимания в load_new_for_triage, не фильтр."""
    patterns = load_profile_role_patterns(conn)
    if not patterns:
        return 0
    with conn.cursor() as cur:
        cur.execute(
            "update telegram_lead set keyword_match = true "
            "where keyword_match = false "
            "and lower(raw_text) like any(%s) "
            "returning lead_id",
            (patterns,),
        )
        return len(cur.fetchall())


def load_new_for_triage(conn, candidate_id: str, limit: int = 20) -> list[dict]:
    """Лиды без строки в telegram_lead_triage для candidate_id (ещё не
    протриажены ИМ конкретным кандидатом), keyword_match первыми."""
    with conn.cursor() as cur:
        cur.execute(
            "select tl.lead_id, tl.channel, tl.permalink, tl.posted_at, tl.raw_text, "
            "tl.keyword_match "
            "from telegram_lead tl "
            "where not exists ("
            "  select 1 from telegram_lead_triage t "
            "  where t.lead_id = tl.lead_id and t.candidate_id = %s"
            ") "
            "order by tl.keyword_match desc, tl.fetched_at asc limit %s",
            (candidate_id, limit),
        )
        rows = cur.fetchall()
    return [
        {"lead_id": str(r[0]), "channel": r[1], "permalink": r[2],
         "posted_at": r[3].isoformat() if r[3] else None, "raw_text": r[4],
         "keyword_match": r[5]}
        for r in rows
    ]


def apply_triage_verdict(conn, lead_id: str, candidate_id: str, is_relevant: bool,
                         extracted: dict | None = None) -> None:
    """Записать вердикт candidate_id по лиду (проставлен ИИ-слоем в сессии через
    MCP). Upsert — повторный триаж того же кандидата обновляет вердикт, не
    падает на конфликте PK (lead_id, candidate_id)."""
    with conn.cursor() as cur:
        cur.execute(
            "insert into telegram_lead_triage "
            "(lead_id, candidate_id, is_relevant, extracted, triaged_at) "
            "values (%s, %s, %s, %s::jsonb, now()) "
            "on conflict (lead_id, candidate_id) do update "
            "set is_relevant = excluded.is_relevant, extracted = excluded.extracted, "
            "triaged_at = now()",
            (lead_id, candidate_id, is_relevant, json.dumps(extracted or {})),
        )
