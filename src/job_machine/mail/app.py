# src/job_machine/mail/app.py
"""FastAPI-воркер job-mail: один эндпоинт /mail/pull, дёргается n8n scheduleTrigger."""
import os

from fastapi import FastAPI

from job_machine.db.connection import connect
from job_machine.mail import imap_client, service
from job_machine.notify.telegram import TelegramSender
from job_machine.pipeline.llm import client_from_env


def create_app(conn_factory=connect, imap_factory=imap_client.connect_from_env,
               llm_factory=client_from_env, sender_factory=None) -> FastAPI:
    app = FastAPI(title="job-machine mail worker")

    def _sender_factory():
        if sender_factory is not None:
            return sender_factory()
        token = os.environ["JOB_NOTIFY_BOT_TOKEN"]
        return TelegramSender(token)

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    @app.post("/mail/pull")
    def pull(body: dict | None = None):
        body = body or {}
        limit = body.get("limit", 25)
        mailbox = os.environ.get("IMAP_USER", "workcockpit@gmail.com")
        owner_chat_id = os.environ["JOB_NOTIFY_OWNER_CHAT_ID"]

        conn = conn_factory()
        imap = imap_factory()
        llm = llm_factory()
        sender = _sender_factory()
        try:
            result = service.poll_and_classify(
                conn, imap=imap, llm=llm, sender=sender, mailbox=mailbox,
                owner_chat_id=owner_chat_id, limit=limit)
        finally:
            imap.logout()
            conn.close()
        return result

    return app


app = create_app()
