"""FastAPI-воркер job-notify. Диспатч управляется расписанием n8n.

Роутинг owner-only: chat_id из env JOB_NOTIFY_OWNER_CHAT_ID.
Токен бота из env JOB_NOTIFY_BOT_TOKEN (см. .env.example; не коммитить реальный).
"""
import os

from fastapi import FastAPI

from job_machine.db.connection import connect
from job_machine.notify import service
from job_machine.notify.telegram import TelegramSender


def _default_sender() -> TelegramSender:
    token = os.environ.get("JOB_NOTIFY_BOT_TOKEN")
    if not token:
        raise RuntimeError("JOB_NOTIFY_BOT_TOKEN не задан (см. .env.example)")
    return TelegramSender(token)


def create_app(conn_factory=connect, sender_factory=_default_sender,
               owner_chat_id: str | None = None) -> FastAPI:
    app = FastAPI(title="job-machine notify worker")
    resolved_chat = owner_chat_id or os.environ.get("JOB_NOTIFY_OWNER_CHAT_ID")

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    @app.post("/notify/dispatch")
    def dispatch():
        if not resolved_chat:
            return {"error": "JOB_NOTIFY_OWNER_CHAT_ID не задан"}
        conn = conn_factory()
        try:
            sender = sender_factory()   # может бросить (нет токена) — conn всё равно закроется
            try:
                return service.dispatch(conn, sender, resolved_chat)
            finally:
                sender.close()
        finally:
            conn.close()

    @app.post("/notify/daily_summary")
    def daily_summary():
        if not resolved_chat:
            return {"error": "JOB_NOTIFY_OWNER_CHAT_ID не задан"}
        conn = conn_factory()
        try:
            sender = sender_factory()   # может бросить (нет токена) — conn всё равно закроется
            try:
                return service.daily_summary(conn, sender, resolved_chat)
            finally:
                sender.close()
        finally:
            conn.close()

    # ─── n8n-send путь: воркер готовит сообщения, отправляет n8n (токен не нужен) ───

    @app.post("/notify/pending")
    def pending():
        if not resolved_chat:
            return {"error": "JOB_NOTIFY_OWNER_CHAT_ID не задан"}
        conn = conn_factory()
        try:
            return {"messages": service.pending_messages(conn, resolved_chat)}
        finally:
            conn.close()

    @app.post("/notify/daily_pending")
    def daily_pending():
        if not resolved_chat:
            return {"error": "JOB_NOTIFY_OWNER_CHAT_ID не задан"}
        conn = conn_factory()
        try:
            return {"messages": service.daily_pending(conn, resolved_chat)}
        finally:
            conn.close()

    @app.post("/notify/summary")
    def summary():
        if not resolved_chat:
            return {"error": "JOB_NOTIFY_OWNER_CHAT_ID не задан"}
        conn = conn_factory()
        try:
            return {"messages": service.summary_now(conn, resolved_chat)}
        finally:
            conn.close()

    return app


app = create_app()
