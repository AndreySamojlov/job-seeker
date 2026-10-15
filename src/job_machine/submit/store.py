"""[SAFETY] DB-слой submit: claim → необратимая граница клика → финализация.

Жизненный цикл заявки идёт строго через submission_attempt: claim берёт её с лизом,
mark_clicking потребляет approval и пересекает необратимую границу, finalize_* пишет
исход по доказательству. Прямой записи state='submitted' в обход доказательства в
этом модуле нет и быть не должно.
События несут confirmation_url + screenshot_path — без сырых ответов формы.
"""
import hashlib
import json
import os
import uuid

from job_machine import audit
from job_machine.browser import blockers as browser_blockers
from job_machine.browser.schema import submission_proof_missing
from job_machine.guards.approval import (
    NoResumeUploadWithoutHashMatch,
    NoSubmitAfterApprovalExpiry,
    NoSubmitIfPayloadHashChanged,
    NoSubmitWithoutApproval,
)
from job_machine.runtime import control as runtime_control


def record_destination_mismatch(conn, application_id: str, expected_url: str,
                                confirmation_url: str) -> None:
    """Пост-submit инвариант (аудит 02.07): confirmation указывает на другой пост.
    Submit уже состоялся — state не откатываем; алерт-блокер + событие владельцу."""
    aid = uuid.UUID(application_id)
    with conn.cursor() as cur:
        cur.execute(
            "update application set current_blocker='destination_mismatch', "
            "updated_at=now() where application_id=%s", (aid,))
    audit.emit_event(conn, "application", aid,
                     "application.submit_destination_mismatch", {
                         "expected_url": expected_url,
                         "confirmation_url": confirmation_url,
                     })


def record_guard_block(conn, application_id: str, guard_result) -> None:
    """STOP submit-гарда: submit_blocked + guard-событие."""
    aid = uuid.UUID(application_id)
    with conn.cursor() as cur:
        cur.execute(
            "update application set state='submit_blocked', submit_status='blocked', "
            "current_blocker=%s, updated_at=now() where application_id=%s",
            (guard_result.guard_name, aid))
    audit.emit_guard_event(conn, "application", aid, guard_result)


def _claim(conn, worker_id: str, lease_seconds: int,
           application_id: str | None = None) -> dict | None:
    """[SAFETY] Атомарно зарезервировать одну одобренную заявку.

    Рубильник читается `for share` в той же транзакции: административное
    выключение не может проскочить между проверкой и резервированием approval.
    `for update ... skip locked` плюс partial unique index ux_submission_attempt_active
    дают at-most-once даже при нескольких воркерах.
    """
    if not runtime_control.is_submit_enabled(conn, for_share=True):
        return None
    id_filter = ""
    params: list = []
    if application_id is not None:
        id_filter = "and a.application_id=%s "
        params.append(uuid.UUID(str(application_id)))
    with conn.cursor() as cur:
        cur.execute(
            "select a.application_id, a.payload_hash, a.resume_artifact_id, "
            "       v.ats_family, appr.approval_id, a.agent_fill_session_id "
            "from application a "
            "join vacancy v on v.vacancy_id=a.vacancy_id "
            "join approval appr on appr.application_id=a.application_id "
            "where a.state='approved' "
            "  and appr.approval_status='approved' "
            "  and appr.reserved_attempt_id is null "
            "  and appr.expires_at > now() "
            "  and appr.payload_hash=a.payload_hash "
            f"{id_filter}"
            "order by a.created_at "
            "for update of a skip locked limit 1",
            tuple(params))
        head = cur.fetchone()
        if head is None:
            return None
        (aid, payload_hash, resume_artifact_id, ats_family, approval_id,
         agent_fill_session_id) = head
        cur.execute(
            "insert into submission_attempt (application_id, approval_id, status, "
            "worker_id, lease_until) "
            "values (%s,%s,'claimed',%s,now() + (%s * interval '1 second')) "
            "returning attempt_id",
            (aid, approval_id, worker_id, lease_seconds))
        attempt_id = cur.fetchone()[0]
        cur.execute(
            "update approval set reserved_attempt_id=%s "
            "where approval_id=%s and approval_status='approved' "
            "and reserved_attempt_id is null returning approval_id",
            (attempt_id, approval_id))
        if cur.fetchone() is None:
            raise RuntimeError("approval reservation lost")
        cur.execute(
            "update application set state='submitting', current_blocker=null, "
            "updated_at=now() where application_id=%s and state='approved' "
            "returning application_id",
            (aid,))
        if cur.fetchone() is None:
            raise RuntimeError("application claim lost")

    with conn.cursor() as cur:
        cur.execute(
            "select artifact_id, artifact_type, path_or_uri, content_hash "
            "from artifact where application_id=%s order by created_at desc",
            (aid,))
        artifacts = cur.fetchall()
    manifest_path = next(
        (path for _id, kind, path, _hash in artifacts if kind == "manifest"), None)
    resume = next(
        ({"path": path, "content_hash": content_hash}
         for artifact_id, kind, path, content_hash in artifacts
         if kind == "resume" and artifact_id == resume_artifact_id),
        None)
    audit.emit_event(conn, "application", aid, "application.submit_claimed", {
        "attempt_id": str(attempt_id),
        "approval_id": str(approval_id),
        "worker_id": worker_id,
    })
    return {
        "application_id": str(aid),
        "attempt_id": str(attempt_id),
        "approval_id": str(approval_id),
        "payload_hash": payload_hash,
        "ats_family": ats_family,
        "manifest_path": manifest_path,
        "resume": resume,
        # Живая сессия агента, если заявку доводил он. Клик обязан идти именно в
        # неё: работа агента существует только на этой странице, а новая навигация
        # её стёрла бы.
        "agent_fill_session_id": agent_fill_session_id,
    }


def claim_next(conn, worker_id: str, lease_seconds: int = 600) -> dict | None:
    return _claim(conn, worker_id, lease_seconds)


def claim_application(conn, application_id: str, worker_id: str,
                      lease_seconds: int = 600) -> dict | None:
    return _claim(conn, worker_id, lease_seconds, application_id)


def mark_clicking(conn, attempt_id: str) -> bool:
    """[SAFETY] Пересечь необратимую границу: потребить approval и зафиксировать клик.

    Все инварианты перепроверяются под блокировкой в одной транзакции — между
    claim и кликом заявка могла дрейфануть. После успешного возврата внешнее
    действие считается начатым, и отменить его нельзя.
    """
    attempt_uuid = uuid.UUID(str(attempt_id))
    with conn.cursor() as cur:
        cur.execute(
            "select sa.application_id, sa.approval_id "
            "from submission_attempt sa "
            "join approval appr on appr.approval_id=sa.approval_id "
            "join application app on app.application_id=sa.application_id "
            "where sa.attempt_id=%s "
            "  and sa.status='claimed' "
            "  and sa.lease_until > now() "
            "  and appr.approval_status='approved' "
            "  and appr.reserved_attempt_id=sa.attempt_id "
            "  and appr.expires_at > now() "
            "  and appr.payload_hash=app.payload_hash "
            "  and app.state='submitting' "
            "for update of sa, appr, app",
            (attempt_uuid,))
        row = cur.fetchone()
        if row is None:
            return False
        _application_id, approval_id = row
        cur.execute(
            "update approval set approval_status='consumed', consumed_at=now() "
            "where approval_id=%s and approval_status='approved' "
            "and reserved_attempt_id=%s returning approval_id",
            (approval_id, attempt_uuid))
        if cur.fetchone() is None:
            raise RuntimeError("approval could not be consumed")
        cur.execute(
            "update submission_attempt set status='clicking', "
            "click_started_at=now(), updated_at=now() "
            "where attempt_id=%s and status='claimed' returning application_id",
            (attempt_uuid,))
        if cur.fetchone() is None:
            raise RuntimeError("submission attempt lost before clicking")
    return True


def fail_claimed_attempt(conn, attempt_id: str, blocker: str, detail: dict) -> bool:
    """Закрыть попытку ДО клика: внешнего эффекта нет, approval освобождается.

    [SAFETY] Регресс C2: раньше approval оставался 'approved' с освобождённым
    reserved_attempt_id — ux_approval_active (0021) не пускал новый
    create_approval, и заявка застревала в submit_blocked без пути наружу.
    Approval, остановивший эту попытку, больше не годен: истекаем его здесь же,
    в той же транзакции, что и блокировку заявки.
    """
    attempt_uuid = uuid.UUID(str(attempt_id))
    code = safe_failure_code(blocker, "broken_flow")
    with conn.cursor() as cur:
        cur.execute(
            "update submission_attempt set status='failed', failure_signal=%s, "
            "resolved_at=now(), resolution_source='system', updated_at=now() "
            "where attempt_id=%s and status='claimed' "
            "returning application_id, approval_id",
            (code, attempt_uuid))
        row = cur.fetchone()
        if row is None:
            return False
        application_id, approval_id = row
        cur.execute(
            "update approval set approval_status='expired', reserved_attempt_id=null, "
            "updated_at=now() where approval_id=%s and approval_status='approved'",
            (approval_id,))
        cur.execute(
            "update application set state='submit_blocked', submit_status='blocked', "
            "current_blocker=%s, updated_at=now() where application_id=%s",
            (blocker, application_id))
    audit.emit_event(conn, "application", application_id,
                     "application.submit_blocked",
                     {"blocker": blocker, "detail": detail,
                      "attempt_id": str(attempt_uuid)})
    return True


def record_orphaned_attempt(conn, application_id: str, attempt_id: str,
                            blocker: str, detail: dict) -> None:
    """[SAFETY] Попытку не удалось закрыть: к моменту финализации она уже не 'claimed'.

    `fail_claimed_attempt` пишет строго по условию `status='claimed'` и на промахе
    возвращает False. Раньше это значение игнорировалось, и транзакция коммитилась
    молча — заявка могла остаться в `submitting` с попыткой в `clicking`, и ни одного
    следа в аудите не оставалось. Состояние здесь НЕ форсируем (кто увёл попытку из
    'claimed' — recover или другой воркер — тот и отвечает за её состояние), но сам
    промах обязан быть видимым.
    """
    audit.emit_event(conn, "application", uuid.UUID(str(application_id)),
                     "application.submit_attempt_orphaned",
                     {"attempt_id": str(attempt_id), "blocker": blocker,
                      "detail": detail})


def can_continue_verification(conn, attempt_id: str) -> bool:
    """Вторая фаза разрешена только для живой попытки с потреблённым approval."""
    with conn.cursor() as cur:
        cur.execute(
            "select 1 from submission_attempt sa "
            "join approval appr on appr.approval_id=sa.approval_id "
            "where sa.attempt_id=%s "
            "and sa.status='clicking' "
            "and sa.click_started_at is not null "
            "and sa.lease_until > now() "
            "and appr.approval_status='consumed' "
            "and appr.reserved_attempt_id=sa.attempt_id",
            (uuid.UUID(str(attempt_id)),))
        return cur.fetchone() is not None


# Классификация страницы браузерным воркером — единый словарь с
# application.current_blocker (captcha, mfa, anti_bot, account_required, login_wall,
# mandatory_unknown, vacancy_removed, ambiguous, broken_flow). Импорт, а не копия:
# новый блокер попадает в allowlist сам и не схлопнется в леджере.
_BROWSER_BLOCKERS = frozenset(browser_blockers.BLOCKERS)

# Доменные блокеры submit-сервиса (submit/service.py::_submit_claim) — не приходят
# из браузера, их выставляет сам конвейер подачи.
_SUBMIT_BLOCKERS = frozenset({
    "manifest_integrity_mismatch",
    "destination_redirect",
})

# Имена submit-гардов: gate.check_submit_gate пишет в блокер именно guard_name.
# "ValidApplicationId" — синтетический STOP самого гейта (класса под него нет).
_GUARD_NAMES = frozenset({
    NoSubmitWithoutApproval.name,
    NoSubmitIfPayloadHashChanged.name,
    NoSubmitAfterApprovalExpiry.name,
    NoResumeUploadWithoutHashMatch.name,
    "ValidApplicationId",
})

# Исходы ПОСЛЕ клика: failure_signal из SubmitResult браузера
# (unmatched|native_invalid|aria_invalid), отсутствие подтверждения, карантин
# неизвестного исхода и протухший лиз (recover_stale_attempts).
_POST_CLICK_SIGNALS = frozenset({
    "no_confirmation", "native_invalid", "aria_invalid", "unmatched",
    "submit_unknown", "timeout", "lease_expired",
})

# [SAFETY] Allowlist защищает БД от неконтролируемой строки, пришедшей со страницы
# работодателя, — но НЕ должен стоить диагностики. Раньше здесь не было ни одного
# реального блокера submit-пути, и captcha/mfa/mandatory_unknown/destination_redirect/
# manifest_integrity_mismatch/имена гардов схлопывались в леджере попыток в
# 'broken_flow': настоящая причина оставалась только в current_blocker и в payload
# события. Каждый источник значений перечислен выше явно.
_SAFE_FAILURE_CODES = (
    _BROWSER_BLOCKERS | _SUBMIT_BLOCKERS | _GUARD_NAMES | _POST_CLICK_SIGNALS
)


def safe_failure_code(value: str | None, fallback: str) -> str:
    """Не пускать в БД произвольный текст ошибки: только известные коды."""
    return value if value in _SAFE_FAILURE_CODES else fallback


def _screenshot_sha256(path: str | None) -> str | None:
    """Хеш физически существующего непустого файла подтверждения."""
    if not path or not os.path.isfile(path):
        return None
    data = open(path, "rb").read()
    if not data:
        return None
    return hashlib.sha256(data).hexdigest()


def finalize_confirmed(conn, attempt_id: str, result,
                       *, resolution_source: str = "browser",
                       resolution_note: str | None = None) -> bool:
    """[SAFETY] Засчитать подачу ТОЛЬКО при полном долговечном доказательстве.

    Возврат False означает «не доказано» и оставляет попытку живой — вызывающий
    обязан затем финализировать её как unknown. Тихого submitted здесь быть не может.
    """
    if submission_proof_missing(result):
        return False
    confirmation_url = getattr(result, "confirmation_url", None)
    confirmation_signal = getattr(result, "confirmation_signal", None)
    screenshot_path = getattr(result, "screenshot_path", None)
    screenshot_hash = _screenshot_sha256(screenshot_path)
    if screenshot_hash is None:
        return False
    attempt_uuid = uuid.UUID(str(attempt_id))
    # [SAFETY] Подъём из 'unknown' разрешён и автоматическому источнику, а не только
    # человеку: recover_stale_attempts могла успеть перевести протухшую попытку в
    # 'unknown' до того, как браузер вернул ПОЛНОЕ доказательство, и тогда старое
    # `status='clicking'` выбрасывало доказанную подачу (confirmation_url, скриншот,
    # хеш) в никуда — finalize_unknown промахивался следом. Порог доказательства при
    # этом не ослаблен: сюда доходят только результаты с пустым
    # submission_proof_missing и существующим непустым файлом скриншота, а переход
    # заявки submit_unknown → submitted ниже разрешён по состоянию с самого начала
    # (`state in ('submitting','submit_unknown')`). Человеческий источник остаётся
    # строго подъёмом из 'unknown': живая 'clicking'-попытка — зона браузера.
    allowed_statuses = ("unknown",) if resolution_source == "human" \
        else ("clicking", "unknown")
    with conn.cursor() as cur:
        cur.execute(
            "update submission_attempt set status='confirmed', "
            "confirmation_url=%s, confirmation_signal=%s, form_absent=true, "
            "errors_absent=true, screenshot_path=%s, unmatched=%s::jsonb, "
            "resolved_at=now(), resolution_source=%s, resolution_note=%s, "
            "updated_at=now() where attempt_id=%s and status = any(%s) "
            "returning application_id",
            (confirmation_url, confirmation_signal, screenshot_path,
             json.dumps(getattr(result, "unmatched", []) or []),
             resolution_source, resolution_note, attempt_uuid,
             list(allowed_statuses)))
        row = cur.fetchone()
        if row is None:
            return False
        application_id = row[0]
        cur.execute(
            "update application set state='submitted', submit_status='submitted', "
            "current_blocker=null, updated_at=now() where application_id=%s "
            "and state in ('submitting','submit_unknown') returning application_id",
            (application_id,))
        if cur.fetchone() is None:
            raise RuntimeError("confirmed attempt could not finalize application")
        cur.execute(
            "insert into artifact (application_id, artifact_type, path_or_uri, "
            "content_hash) values (%s,'confirmation',%s,%s)",
            (application_id, screenshot_path, screenshot_hash))
    audit.emit_event(conn, "application", application_id, "application.submitted", {
        "attempt_id": str(attempt_uuid),
        "confirmation_url": confirmation_url,
        "confirmation_signal": confirmation_signal,
        "screenshot_sha256": screenshot_hash,
        "resolution_source": resolution_source,
    })
    return True


def finalize_unknown(conn, attempt_id: str, result, reason: str) -> bool:
    """Клик состоялся, доказательства нет. Автоматического retry для unknown нет."""
    attempt_uuid = uuid.UUID(str(attempt_id))
    code = safe_failure_code(reason, "submit_unknown")
    with conn.cursor() as cur:
        cur.execute(
            "update submission_attempt set status='unknown', failure_signal=%s, "
            "unmatched=%s::jsonb, resolved_at=now(), resolution_source='system', "
            "updated_at=now() where attempt_id=%s and status in ('clicking','claimed') "
            "returning application_id",
            (code, json.dumps(getattr(result, "unmatched", []) or []), attempt_uuid))
        row = cur.fetchone()
        if row is None:
            return False
        application_id = row[0]
        cur.execute(
            "update application set state='submit_unknown', submit_status='unknown', "
            "current_blocker='submit_unknown', updated_at=now() "
            "where application_id=%s", (application_id,))
    audit.emit_event(conn, "application", application_id,
                     "application.submit_unknown",
                     {"attempt_id": str(attempt_uuid), "reason": code})
    return True


def finalize_not_submitted(conn, attempt_id: str, result, reason: str) -> bool:
    """[SAFETY] Достижимо только после mark_clicking, то есть после начала внешнего
    действия. Слова браузера «я не подал» недостаточно, чтобы утверждать, что клик
    не имел эффекта, поэтому хранилище честно падает в unknown."""
    return finalize_unknown(conn, attempt_id, result, reason)


def recover_stale_attempts(conn) -> dict:
    """[SAFETY] Развести две принципиально разные ситуации протухшего лиза.

    `claimed` — клика не было, внешнего эффекта нет: попытку закрываем,
    approval освобождаем, заявка возвращается в очередь на подачу.
    `clicking` — клик начат, эффект неизвестен: возврат в очередь означал бы
    риск двойной подачи, поэтому карантин в submit_unknown.
    """
    # Единый порядок с остальными путями: ни одна запись в failure_signal не
    # обходит allowlist, даже когда код — литерал в этом же файле.
    released_code = safe_failure_code("lease_expired", "broken_flow")
    quarantined_code = safe_failure_code("submit_unknown", "broken_flow")
    released = 0
    quarantined = 0
    with conn.cursor() as cur:
        cur.execute(
            "select attempt_id, application_id, approval_id, status "
            "from submission_attempt "
            "where status in ('claimed','clicking') and lease_until <= now() "
            "for update skip locked")
        rows = cur.fetchall()

    for attempt_id, application_id, approval_id, status in rows:
        if status == "claimed":
            with conn.cursor() as cur:
                cur.execute(
                    "update submission_attempt set status='failed', "
                    "failure_signal=%s, resolved_at=now(), "
                    "resolution_source='system', updated_at=now() "
                    "where attempt_id=%s", (released_code, attempt_id))
                cur.execute(
                    "update approval set reserved_attempt_id=null "
                    "where approval_id=%s and reserved_attempt_id=%s",
                    (approval_id, attempt_id))
                cur.execute(
                    "update application set state='approved', updated_at=now() "
                    "where application_id=%s and state='submitting'",
                    (application_id,))
            audit.emit_event(conn, "application", application_id,
                             "application.submit_lease_released",
                             {"attempt_id": str(attempt_id)})
            released += 1
        else:
            with conn.cursor() as cur:
                cur.execute(
                    "update submission_attempt set status='unknown', "
                    "failure_signal=%s, resolved_at=now(), "
                    "resolution_source='system', updated_at=now() "
                    "where attempt_id=%s", (quarantined_code, attempt_id))
                cur.execute(
                    "update application set state='submit_unknown', "
                    "submit_status='unknown', current_blocker='submit_unknown', "
                    "updated_at=now() where application_id=%s", (application_id,))
            audit.emit_event(conn, "application", application_id,
                             "application.submit_unknown",
                             {"attempt_id": str(attempt_id), "reason": "lease_expired"})
            quarantined += 1
    return {"released": released, "quarantined": quarantined}
