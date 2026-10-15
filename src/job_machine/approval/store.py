"""[SAFETY] DB-слой approval: pull заявок без токена, create/approve/reject, load для гарда.

Токен генерируется secrets.token_hex(32) в service.py — здесь только запись/чтение.
События несут approval_id + payload_hash — без сырых ответов формы.
"""
import uuid

from job_machine import audit


def pull_needs_approval(conn, limit: int) -> list[dict]:
    """Заявки pre_submit_ready без существующей approval-записи."""
    with conn.cursor() as cur:
        cur.execute(
            "select a.application_id, a.payload_hash, v.company, v.title "
            "from application a join vacancy v on v.vacancy_id = a.vacancy_id "
            "left join approval appr on appr.application_id = a.application_id "
            "where a.state = 'pre_submit_ready' and appr.approval_id is null "
            "order by a.created_at limit %s",
            (limit,))
        return [{"application_id": str(r[0]), "payload_hash": r[1],
                 "company": r[2] or "", "role": r[3] or ""} for r in cur.fetchall()]


def create_approval(conn, application_id: str, payload_hash: str,
                    token: str, expires_at) -> str:
    """Создать pending approval record; вернуть approval_id (строка UUID).

    [SAFETY] Ленивая очистка перед INSERT (0021 регресс C2): ux_approval_active
    допускает не больше одной активной ('pending'/'approved') строки на заявку,
    но ни один код-путь в проекте не пишет approval_status='expired' по факту
    протухания TTL или блокировки подачи — см. fail_claimed_attempt. Без этой
    очистки застрявшая активная строка (протухший pending ИЛИ approved от
    гардом остановленной попытки, чей payload_hash с тех пор уехал) навсегда
    роняет create_approval с IntegrityError. Здесь мы истекаем только заведомо
    неактуальные строки — protégé TTL или payload drift — той же формулой, что
    уже применяла миграция 0021 при реконсиляции. 'consumed'/'rejected'/уже
    'expired' строки не трогаются: это append-only аудит-история.
    """
    aid = uuid.UUID(application_id)
    with conn.cursor() as cur:
        cur.execute(
            "update approval set approval_status='expired', updated_at=now() "
            "where application_id=%s and approval_status in ('pending','approved') "
            "and (expires_at is null or expires_at <= now() or payload_hash <> %s) "
            "returning approval_id",
            (aid, payload_hash))
        stale_ids = [r[0] for r in cur.fetchall()]
        cur.execute(
            "insert into approval (application_id, approval_type, payload_hash, "
            "approval_status, approval_token, expires_at) "
            "values (%s,'submit',%s,'pending',%s,%s) returning approval_id",
            (aid, payload_hash, token, expires_at))
        approval_id = cur.fetchone()[0]
    if stale_ids:
        audit.emit_event(conn, "application", aid, "application.approval_expired", {
            "approval_ids": [str(i) for i in stale_ids],
            "reason": "stale_or_drifted_before_new_request",
        })
    audit.emit_event(conn, "application", aid, "application.approval_requested", {
        "approval_id": str(approval_id),
        "payload_hash": payload_hash,
        "expires_at": expires_at.isoformat() if hasattr(expires_at, "isoformat") else str(expires_at),
    })
    return str(approval_id)


def approve(conn, application_id: str) -> bool:
    """Одобрить pending approval, СВЕРИВ payload_hash с текущим payload заявки.

    [SAFETY] Под моделью угроз «мисфайр своего кода» нельзя доверять вызывающему
    передать корректный hash — читаем оба значения из БД сами. approval.payload_hash
    (раскрытый при request_approval) должен всё ещё равняться application.payload_hash;
    иначе payload дрейфанул между раскрытием и одобрением → не одобряем, audit-событие.
    False если нет pending ИЛИ payload дрейфанул.
    """
    aid = uuid.UUID(application_id)
    with conn.cursor() as cur:
        cur.execute(
            "select appr.approval_id, appr.payload_hash, a.payload_hash "
            "from approval appr "
            "join application a on a.application_id = appr.application_id "
            "where appr.application_id=%s and appr.approval_status='pending' "
            "order by appr.expires_at desc nulls last limit 1",
            (aid,))
        row = cur.fetchone()
    if row is None:
        return False
    approval_id, disclosed_hash, current_hash = row
    if disclosed_hash != current_hash:
        audit.emit_event(conn, "application", aid,
                         "application.approval_payload_drift", {
                             "approval_id": str(approval_id),
                             "disclosed_payload_hash": disclosed_hash,
                             "current_payload_hash": current_hash,
                         })
        return False
    with conn.cursor() as cur:
        cur.execute(
            "update approval set approval_status='approved', approved_at=now() "
            "where approval_id=%s and approval_status='pending' "
            "returning approval_id",
            (approval_id,))
        if cur.fetchone() is None:
            return False
        # Контракт 0021: одобрение — переход состояния, а не пометка сбоку.
        # claim в submit/store забирает только state='approved'.
        cur.execute(
            "update application set state='approved', current_blocker=null, "
            "updated_at=now() where application_id=%s "
            "and state in ('pre_submit_ready','awaiting_approval') "
            "returning application_id",
            (aid,))
        if cur.fetchone() is None:
            # [SAFETY] Заявка успела уйти из approvable state (submit_blocked,
            # fill_blocked и т.п.) между request_approval и этим approve —
            # реалистичный триггер: заявка в submit_blocked/fill_blocked с
            # висящим одобрением. Откатываем approval-строку обратно в
            # 'pending', а не оставляем её 'approved': submit-claim требует ОБА
            # условия сразу (application.state='approved' И
            # approval.approval_status='approved') — approved-approval без
            # соответствующего application.state была бы молчаливым, никогда
            # не реализуемым несоответствием в аудите. Структурированный отказ
            # вместо голого исключения — тот же контракт, что и у ветки
            # payload_hash-дрейфа выше: вызывающий (mcp/tools.py) исключений
            # не ловит.
            cur.execute(
                "select state from application where application_id=%s", (aid,))
            current_state = cur.fetchone()[0]
            cur.execute(
                "update approval set approval_status='pending', approved_at=null "
                "where approval_id=%s", (approval_id,))
            audit.emit_event(conn, "application", aid,
                             "application.approve_rejected_invalid_state", {
                                 "approval_id": str(approval_id),
                                 "state": current_state,
                             })
            return False
    audit.emit_event(conn, "application", aid, "application.approved",
                     {"approval_id": str(approval_id)})
    return True


def reject(conn, application_id: str, reason: str = "") -> bool:
    """Отклонить pending approval; заблокировать заявку. False если нет pending."""
    aid = uuid.UUID(application_id)
    with conn.cursor() as cur:
        cur.execute(
            "update approval set approval_status='rejected' "
            "where application_id=%s and approval_status='pending' "
            "returning approval_id",
            (aid,))
        row = cur.fetchone()
    if row is None:
        return False
    audit.emit_event(conn, "application", aid, "application.rejected",
                     {"approval_id": str(row[0]), "reason": reason})
    with conn.cursor() as cur:
        cur.execute(
            "update application set state='fill_blocked', "
            "current_blocker='approval_rejected', updated_at=now() "
            "where application_id=%s",
            (aid,))
    return True


def load_by_application(conn, application_id: str) -> dict | None:
    """Загрузить последний approval record для GuardContext (или None если нет)."""
    with conn.cursor() as cur:
        cur.execute(
            "select approval_status, approval_token, payload_hash, expires_at, approved_at "
            "from approval where application_id=%s "
            "order by expires_at desc nulls last limit 1",
            (uuid.UUID(application_id),))
        row = cur.fetchone()
    if row is None:
        return None
    status, token, phash, expires_at, approved_at = row
    return {
        "approval_status": status,
        "approval_token": token,
        "payload_hash": phash,
        "expires_at": expires_at,
        "approved_at": approved_at,
    }
