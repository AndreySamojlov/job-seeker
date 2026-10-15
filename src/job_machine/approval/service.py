"""Approval lifecycle: request (mint pending) → approve/reject.

approval_token (secrets.token_hex(32) → 64-char hex) — audit-коррелятор записи
одобрения, НЕ secret-capability. Реальный submit-инвариант (CLAUDE.md §3): явное
человеческое approved + payload_hash-связь disclosed↔current + не истёкший TTL.
"""
import secrets
from datetime import datetime, timedelta, timezone

from job_machine.approval import store

DEFAULT_TTL_HOURS = 24


def request_approval(conn, application_id: str, payload_hash: str,
                     ttl_hours: int = DEFAULT_TTL_HOURS) -> str:
    """Создать pending approval record с новым токеном. Вернуть approval_id."""
    token = secrets.token_hex(32)
    expires_at = datetime.now(tz=timezone.utc) + timedelta(hours=ttl_hours)
    return store.create_approval(conn, application_id, payload_hash, token, expires_at)


def process_approval_request(conn, limit: int = 10) -> dict:
    """Создать approval records для всех pre_submit_ready без pending."""
    rows = store.pull_needs_approval(conn, limit)
    created = []
    for row in rows:
        approval_id = request_approval(conn, row["application_id"], row["payload_hash"])
        conn.commit()
        created.append({
            "application_id": row["application_id"],
            "approval_id": approval_id,
            "company": row["company"],
            "role": row["role"],
        })
    return {"count": len(created), "items": created}
