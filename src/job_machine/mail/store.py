"""DB-слой job-mail: курсор IMAP, ledger писем, активные заявки, запись исхода.

Паттерн — как submit/store.py: update + audit.emit_event в одной функции,
коммит на стороне вызывающего (service.py).
"""
import uuid

from job_machine import audit
from job_machine.mail.models import ApplicationRef


def get_cursor(conn, mailbox: str) -> int:
    with conn.cursor() as cur:
        cur.execute("select last_uid from mail_cursor where mailbox=%s", (mailbox,))
        row = cur.fetchone()
        return row[0] if row else 0


def set_cursor(conn, mailbox: str, last_uid: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "insert into mail_cursor (mailbox, last_uid) values (%s, %s) "
            "on conflict (mailbox) do update set last_uid=excluded.last_uid",
            (mailbox, last_uid))


def load_active_applications(conn) -> list[ApplicationRef]:
    """Поданные заявки без терминального исхода письма — контекст для LLM-матчинга.

    Закрытость заявки для матчинга теперь определяется не сменой `state`
    (state остаётся 'submitted' и после отказа — миграция 0021, подача не
    отменяется отказом), а колонкой `outcome_status`: её проставляет та же
    `record_reply_outcome` в момент, когда воркер уже зафиксировал rejected/
    interview_scheduled. Поэтому фильтр — `state='submitted' AND outcome_status
    IS NULL`: заявка с уже записанным исходом не должна снова участвовать
    в сопоставлении входящих писем и получать перезапись от постороннего письма.
    """
    with conn.cursor() as cur:
        cur.execute(
            "select a.application_id, a.candidate_id, v.company, v.title "
            "from application a join vacancy v on v.vacancy_id = a.vacancy_id "
            "where a.state = 'submitted' and a.outcome_status is null")
        return [
            ApplicationRef(application_id=str(r[0]), candidate_id=r[1],
                           company=r[2] or "", role=r[3] or "")
            for r in cur.fetchall()
        ]


def record_reply_outcome(conn, application_id: str, category: str) -> None:
    """category ∈ {'rejected', 'interview_scheduled'}. Записать исход работодателя
    и эмитировать событие для notify-конвейера (EVENT_KIND в notify/models.py).

    Исход живёт в отдельных колонках (миграция 0021), а не в state: подача уже
    состоялась, и отказ её не отменяет. Констрейнт application_outcome_chk
    допускает ровно эти два значения.
    """
    aid = uuid.UUID(application_id)
    with conn.cursor() as cur:
        cur.execute(
            "update application set outcome_status=%s, outcome_source='mail', "
            "outcome_confirmed_at=now(), updated_at=now() "
            "where application_id=%s", (category, aid))
    audit.emit_event(conn, "application", aid,
                     f"application.{category}", {"source": "mail"})


def insert_inbound_email(conn, *, mailbox: str, uid: int, from_addr: str,
                         subject: str, body_excerpt: str,
                         candidate_id: str | None, application_id: str | None,
                         category: str, confidence: float, status: str) -> None:
    aid = uuid.UUID(application_id) if application_id else None
    with conn.cursor() as cur:
        cur.execute(
            "insert into inbound_email (mailbox, uid, from_addr, subject, "
            "  body_excerpt, candidate_id, application_id, category, "
            "  confidence, status) "
            "values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "on conflict (mailbox, uid) do nothing",
            (mailbox, uid, from_addr, subject, body_excerpt, candidate_id,
             aid, category, confidence, status))
