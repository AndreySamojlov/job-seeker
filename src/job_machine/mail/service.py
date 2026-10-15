"""Оркестрация job-mail: детерминированный pull → LLM classify → apply/needs_review.

Приоритет применения per-item — как triage/service.py: каждое письмо коммитится
отдельно, ошибка на одном письме не блокирует остальные.
"""
from html import escape

from job_machine.mail import store
from job_machine.mail.imap_client import fetch_new_messages


CONFIDENCE_THRESHOLD = 0.7


def _needs_review_text(email) -> str:
    return (
        f"📬 <b>Письмо требует разбора</b>\n"
        f"От: {escape(email.from_addr)}\n"
        f"Тема: {escape(email.subject)}\n"
        "Матч заявки не найден или классификация неуверенная — "
        "смотри inbound_email в БД."
    )


def poll_and_classify(conn, *, imap, llm, sender, mailbox: str,
                      owner_chat_id: str, fetch_fn=fetch_new_messages,
                      limit: int = 25) -> dict:
    last_uid = store.get_cursor(conn, mailbox)
    emails = fetch_fn(imap, last_uid, limit=limit)
    applied = needs_review = 0
    max_uid = last_uid

    for email in emails:
        try:
            applications = store.load_active_applications(conn)
            known_application_ids = {a.application_id for a in applications}
            known_candidate_ids = {a.candidate_id for a in applications}
            verdict = llm.classify_reply(email, applications)

            # Строгий фильтр против галлюцинаций LLM — как resume_phrasing фильтрует
            # aid по `allowed` в pipeline/llm.py. Несопоставленный id не только даёт
            # неверный исход, но и валит insert_inbound_email на FK-констрейнте
            # (application_id/candidate_id ссылаются на реальные таблицы), что без
            # этого фильтра навсегда стопорит курсор на одном письме.
            application_id = verdict.application_id
            if application_id is not None and application_id not in known_application_ids:
                application_id = None
            candidate_id = verdict.candidate_id
            if candidate_id is not None and candidate_id not in known_candidate_ids:
                candidate_id = None

            is_confident = (
                verdict.category in ("rejected", "interview_scheduled")
                and application_id is not None
                and verdict.confidence >= CONFIDENCE_THRESHOLD
            )
            if is_confident:
                store.record_reply_outcome(conn, application_id, verdict.category)
                status = "applied"
                applied += 1
            else:
                sender.send_message(owner_chat_id, _needs_review_text(email))
                status = "needs_review"
                needs_review += 1

            store.insert_inbound_email(
                conn, mailbox=mailbox, uid=email.uid, from_addr=email.from_addr,
                subject=email.subject, body_excerpt=email.body[:2000],
                candidate_id=candidate_id, application_id=application_id,
                category=verdict.category, confidence=verdict.confidence, status=status)
        except Exception:
            # Настоящая изоляция per-item (докстринг это обещает): непредвиденный сбой
            # на одном письме (кривой JSON от LLM, временная ошибка БД) не должен
            # блокировать курсор навечно — письмо помечается needs_review без
            # id-полей (безопасно относительно FK) и уходит на ручной разбор.
            conn.rollback()
            store.insert_inbound_email(
                conn, mailbox=mailbox, uid=email.uid, from_addr=email.from_addr,
                subject=email.subject, body_excerpt=email.body[:2000],
                candidate_id=None, application_id=None,
                category="other", confidence=0.0, status="needs_review")
            sender.send_message(owner_chat_id, _needs_review_text(email))
            needs_review += 1

        max_uid = max(max_uid, email.uid)
        store.set_cursor(conn, mailbox, max_uid)
        conn.commit()

    return {"applied": applied, "needs_review": needs_review, "total": len(emails)}
