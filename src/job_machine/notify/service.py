"""Оркестрация оповещений. dispatch: событийные (claim→send→mark, at-least-once,
ретрай pending). daily_summary: раз в сутки, дедуп по дате.
"""
import datetime
import logging

from job_machine.notify import render, store

log = logging.getLogger(__name__)


def dispatch(conn, sender, owner_chat_id: str) -> dict:
    rows = store.select_pending(conn)
    sent = skipped = failed = 0
    for row in rows:
        try:
            kind, text = render.render_event(row)
        except Exception as exc:   # неизвестный тип/битый row — не роняем тик
            log.warning("render не удался для %s: %s", row.get("event_id"), exc)
            skipped += 1
            continue
        store.claim(conn, row["event_id"], kind, owner_chat_id)
        conn.commit()
        try:
            mid = sender.send_message(owner_chat_id, text)
        except Exception as exc:
            log.warning("send не удался для %s: %s", row["event_id"], exc)
            failed += 1        # строка осталась pending → ретрай следующим тиком
            continue
        store.mark_sent(conn, row["event_id"], mid)
        conn.commit()
        sent += 1
    return {"sent": sent, "skipped": skipped, "failed": failed}


def _stats_digest(conn, d) -> tuple[str, int]:
    """Отрендерить дневную сводку на дату d. Общий шаг daily_summary/daily_pending/
    summary_now — держит формат сводки в одном месте."""
    stats = store.daily_stats(conn)
    return render.render_daily(stats, str(d)), len(stats)


def daily_summary(conn, sender, owner_chat_id: str, now=None) -> dict:
    now = now or datetime.datetime.now(datetime.timezone.utc)
    d = now.date()
    if store.daily_exists(conn, d):
        return {"status": "already_sent", "date": str(d)}
    text, count = _stats_digest(conn, d)
    mid = sender.send_message(owner_chat_id, text)   # исключение → ретрай след. тиком
    store.record_daily(conn, d, owner_chat_id, mid)
    conn.commit()
    return {"status": "sent", "date": str(d), "candidates": count}


# ─── n8n-send путь (отправку делает n8n Telegram-нодой; воркеру токен не нужен) ───

def pending_messages(conn, owner_chat_id: str) -> list[dict]:
    """Вернуть готовые сообщения [{chat_id, text}] для недоставленных кураторских
    событий и сразу пометить их доставленными (ledger-дедуп). Саму отправку делает
    n8n. at-most-once: редкая потеря при сбое n8n между выдачей и отправкой
    приемлема для инфо-сообщений (дубли между тиками ledger исключает)."""
    rows = store.select_pending(conn)
    out = []
    for row in rows:
        try:
            kind, text = render.render_event(row)
        except Exception as exc:   # неизвестный тип/битый row — не роняем тик
            log.warning("render не удался для %s: %s", row.get("event_id"), exc)
            continue
        store.mark_delivered(conn, row["event_id"], kind, owner_chat_id)
        out.append({"chat_id": owner_chat_id, "text": text})
    conn.commit()
    return out


def daily_pending(conn, owner_chat_id: str, now=None) -> list[dict]:
    """Дневная сводка для n8n-send: [{chat_id, text}] или [] если уже слали сегодня.
    Дату фиксируем сразу (дедуп по дате)."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    d = now.date()
    if store.daily_exists(conn, d):
        return []
    text, _ = _stats_digest(conn, d)
    store.record_daily(conn, d, owner_chat_id, None)
    conn.commit()
    return [{"chat_id": owner_chat_id, "text": text}]


def summary_now(conn, owner_chat_id: str, now=None) -> list[dict]:
    """Сводка по требованию владельца (команда /summary в TG). В отличие от
    daily_pending — не гейтится и не пишет дневной дедуп-ledger: можно дёргать
    сколько угодно раз, не мешая плановой утренней сводке."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    text, _ = _stats_digest(conn, now.date())
    return [{"chat_id": owner_chat_id, "text": text}]
