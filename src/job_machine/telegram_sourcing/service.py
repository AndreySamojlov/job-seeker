"""Оркестрация фетч-прохода по Telegram-каналам (детерминированный слой — без ИИ).

Изоляция по каналу: exception на одном канале не роняет прогон остальных.
Канал, чей последний результат — подтверждённый 404 ('not_found'), пропускается
без повторного запроса на следующих прогонах (404 у публичного канала — почти
необратимый сигнал, в отличие от транзиентной сетевой ошибки, которая просто
повторится на следующем плановом прогоне без специальной логики).
"""
from dataclasses import dataclass, field

from job_machine.discovery.throttle import record_fetch
from job_machine.telegram_sourcing import store
from job_machine.telegram_sourcing.parser import parse_messages


def _last_status(conn, source_key: str) -> str | None:
    with conn.cursor() as cur:
        cur.execute(
            "select last_status from source_fetch_state where source_key = %s",
            (source_key,),
        )
        row = cur.fetchone()
    return row[0] if row else None


@dataclass
class FetchSummary:
    channels_processed: int = 0
    channels_skipped: int = 0
    channels_not_found: int = 0
    channels_error: int = 0
    leads_inserted: int = 0
    leads_duplicate: int = 0
    errors: list[str] = field(default_factory=list)


def run_fetch(conn, client, channels) -> FetchSummary:
    summary = FetchSummary()
    for spec in channels:
        source_key = f"telegram:{spec.handle}"
        if _last_status(conn, source_key) == "not_found":
            summary.channels_skipped += 1
            continue
        try:
            html = client.fetch_channel_html(spec.handle)
            if html is None:
                record_fetch(conn, source_key, "not_found")
                summary.channels_not_found += 1
                continue
            messages = parse_messages(html, spec.handle)
            inserted = 0
            duplicate = 0
            for msg in messages:
                if store.upsert_lead(conn, msg):
                    inserted += 1
                else:
                    duplicate += 1
            conn.commit()
            record_fetch(conn, source_key, "ok")
            summary.channels_processed += 1
            summary.leads_inserted += inserted
            summary.leads_duplicate += duplicate
        except Exception as exc:
            conn.rollback()
            record_fetch(conn, source_key, "error")
            summary.channels_error += 1
            summary.errors.append(f"{spec.handle}: {exc}")
    store.apply_keyword_match(conn)
    conn.commit()
    return summary
