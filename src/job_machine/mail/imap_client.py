"""Детерминированный IMAP-фетч новых писем. Без LLM/DB — легко тестируется
через fake IMAP4-совместимый объект (duck typing по методам login/select/
uid_search/uid_fetch/logout).
"""
from __future__ import annotations

import email
import os
from email.header import decode_header
from imaplib import IMAP4_SSL

from job_machine.mail.models import EmailInput


def _decode(value: str | None) -> str:
    if not value:
        return ""
    parts = decode_header(value)
    out = []
    for text, enc in parts:
        if isinstance(text, bytes):
            out.append(text.decode(enc or "utf-8", errors="replace"))
        else:
            out.append(text)
    return "".join(out)


def _extract_body(msg) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and not part.get_filename():
                payload = part.get_payload(decode=True) or b""
                charset = part.get_content_charset() or "utf-8"
                return payload.decode(charset, errors="replace")
        return ""
    payload = msg.get_payload(decode=True) or b""
    charset = msg.get_content_charset() or "utf-8"
    return payload.decode(charset, errors="replace")


def connect_from_env(env: dict | None = None) -> IMAP4_SSL:
    """Открыть IMAP-соединение из IMAP_HOST/IMAP_PORT/IMAP_USER/IMAP_APP_PASSWORD."""
    source = env if env is not None else os.environ
    host = source["IMAP_HOST"]
    port = int(source.get("IMAP_PORT", "993"))
    user = source["IMAP_USER"]
    password = source["IMAP_APP_PASSWORD"]
    conn = IMAP4_SSL(host, port)
    conn.login(user, password)
    return conn


def list_recent_headers(imap, limit: int = 30) -> list[dict]:
    """Заголовки (uid/date/from/subject) последних `limit` писем, без тела и без
    привязки к `last_uid` — для ручной проверки ящика (`scripts/check_mailbox.py`),
    в отличие от `fetch_new_messages` не двигает курсор и не читает тело письма.
    """
    imap.select("INBOX", readonly=True)
    typ, data = imap.uid("search", None, "ALL")
    if typ != "OK" or not data or not data[0]:
        return []
    uids = sorted(int(u) for u in data[0].split())[-limit:]
    out: list[dict] = []
    for uid in uids:
        typ, msg_data = imap.uid("fetch", str(uid), "(BODY.PEEK[HEADER.FIELDS (DATE FROM SUBJECT)])")
        if typ != "OK" or not msg_data or msg_data[0] is None:
            continue
        raw = msg_data[0][1]
        msg = email.message_from_bytes(raw)
        out.append({
            "uid": uid,
            "date": _decode(msg.get("Date")),
            "from_addr": _decode(msg.get("From")),
            "subject": _decode(msg.get("Subject")),
        })
    return out


def fetch_new_messages(imap, last_uid: int, limit: int = 25) -> list[EmailInput]:
    """Письма с UID > last_uid, максимум limit штук, в порядке возрастания UID.

    imap — открытое IMAP4_SSL-подобное соединение (select уже не выполнен).
    """
    imap.select("INBOX", readonly=True)
    typ, data = imap.uid("search", None, f"UID {last_uid + 1}:*")
    if typ != "OK":
        return []
    uids = [int(u) for u in data[0].split() if int(u) > last_uid]
    uids.sort()
    uids = uids[:limit]
    out: list[EmailInput] = []
    for uid in uids:
        typ, msg_data = imap.uid("fetch", str(uid), "(RFC822)")
        if typ != "OK" or not msg_data or msg_data[0] is None:
            continue
        raw = msg_data[0][1]
        msg = email.message_from_bytes(raw)
        out.append(EmailInput(
            uid=uid,
            from_addr=_decode(msg.get("From")),
            subject=_decode(msg.get("Subject")),
            body=_extract_body(msg)[:2000],
        ))
    return out
