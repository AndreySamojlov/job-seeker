"""DB-слой агент-пути: прочитать живую agent_fill_pending сессию / зафиксировать исход.

agent_fill_pending = код не сопоставил часть required-полей, страница передана
языковой модели-агенту по CDP (Task 7 плана agent-driven fill). Как и handoff_store —
НЕ submit-путь: тут только чтение состояния и запись исхода (done/blocked).
"""
import uuid

from job_machine import audit


def load_agent_fill(conn, application_id: str) -> dict | None:
    """Заявка в agent_fill_pending: сессия, URL страницы, несопоставленные поля.

    None — заявки нет, ИЛИ она сейчас не в state='agent_fill_pending' (сессия уже
    зафиксирована/освобождена, либо заявка обработана иначе).
    """
    aid = uuid.UUID(str(application_id))
    with conn.cursor() as cur:
        cur.execute(
            "select state, agent_fill_session_id, agent_fill_started_at "
            "from application where application_id=%s", (aid,))
        row = cur.fetchone()
        if row is None or row[0] != "agent_fill_pending":
            return None
        cur.execute(
            "select payload_json from event "
            "where entity_type='application' and entity_id=%s "
            "  and event_type='application.agent_fill_pending' "
            "order by created_at desc limit 1", (aid,))
        ev = cur.fetchone()
    payload = ev[0] if ev else {}
    return {
        "session_id": row[1],
        "started_at": row[2],
        "page_url": payload.get("page_url"),
        "unmatched": payload.get("unmatched", []),
    }


def record_agent_fill_done(conn, application_id: str, session_id: str) -> bool:
    """Агент честно добил форму (пустой остаток при повторной инспекции) →
    заявка возвращается в обычный конвейер на pre_submit_ready.

    agent_fill_session_id СОХРАНЯЕТСЯ: по нему submit-воркер находит ту же живую
    страницу и кликает именно там. Обнулить его здесь значило бы потерять всё, что
    заполнил агент — воркер открыл бы новую сессию и заново навигировал (найдено
    на живом прогоне OKX 2026-08-07). Страницу освобождает submit после клика; если
    до клика не дошло, её подберёт таймаут-свип, который ищет по session_id, а не
    по состоянию заявки. agent_fill_started_at тоже сохраняется — это часы свипа."""
    aid = uuid.UUID(str(application_id))
    with conn.cursor() as cur:
        cur.execute(
            "update application set state='pre_submit_ready', "
            "fill_status='pre_submit_ready', current_blocker=null, "
            "updated_at=now() where application_id=%s "
            "and state='agent_fill_pending' and agent_fill_session_id=%s",
            (aid, session_id))
        if cur.rowcount != 1:
            return False
    audit.emit_event(conn, "application", aid, "application.agent_fill_done", {})
    return True


def record_agent_fill_blocked(conn, application_id: str, reason: str, session_id: str) -> bool:
    """Агент не может честно добить форму (missing_fact/captcha/mfa/account_required/
    timeout) → терминальный стоп, как обычный fill_blocked, но со своим событием
    (различимо в аудите от детерминированных STOP-гардов fill/store.py)."""
    aid = uuid.UUID(str(application_id))
    with conn.cursor() as cur:
        cur.execute(
            "update application set state='fill_blocked', fill_status='blocked', "
            "current_blocker=%s, updated_at=now() where application_id=%s "
            "and state='agent_fill_pending' and agent_fill_session_id=%s",
            (reason, aid, session_id))
        if cur.rowcount != 1:
            return False
    audit.emit_event(conn, "application", aid, "application.agent_fill_blocked",
                     {"reason": reason})
    return True
