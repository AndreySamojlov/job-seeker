"""DB-слой handoff_browser: определение целевого URL и запись handoff_manual.

handoff = передача живой сессии человеку под CAPTCHA/MFA. НЕ обход, НЕ submit.
"""
import uuid

from job_machine import audit
from job_machine.fill.store import load_manifest


def load_destination_url(conn, application_id: str) -> str | None:
    """Вернуть URL назначения для handoff-навигации.

    Приоритет:
    1. manifest.destination_url (из PackageManifest — самый точный URL формы).
    2. vacancy.canonical_url (фолбэк если manifest недоступен).
    3. None если ни то ни другое неизвестно.
    """
    with conn.cursor() as cur:
        cur.execute(
            "select art.path_or_uri, v.canonical_url "
            "from application a "
            "join vacancy v on v.vacancy_id = a.vacancy_id "
            "left join artifact art on art.application_id = a.application_id "
            "  and art.artifact_type = 'manifest' "
            "where a.application_id = %s "
            "limit 1",
            (application_id,),
        )
        row = cur.fetchone()

    if row is None:
        return None

    manifest_path, canonical_url = row

    # Попытка прочитать destination_url из manifest
    if manifest_path:
        try:
            manifest = load_manifest(manifest_path)
            if manifest.destination_url:
                return manifest.destination_url
        except (OSError, ValueError):
            pass

    # Фолбэк на canonical_url из vacancy
    return canonical_url or None


def record_handoff_manual(conn, application_id: str, novnc_url: str | None,
                          session_id: str) -> None:
    """Пометить заявку как находящуюся в ручном handoff и эмитировать audit-событие.

    Ставит state='fill_blocked' + current_blocker='handoff_manual'. Отдельного
    состояния handoff_manual больше нет: констрейнт application_state_canonical_chk
    (миграция 0021) допускает только каноничный домен, и та же миграция перевела
    существующие строки ровно в эту пару. Сигнал "ждёт человека у браузера" несёт
    current_blocker — на него и смотрят потребители (notify/store.py).
    """
    aid = uuid.UUID(str(application_id))
    with conn.cursor() as cur:
        cur.execute(
            "update application "
            "set state='fill_blocked', current_blocker='handoff_manual', "
            "    updated_at=now() "
            "where application_id=%s",
            (aid,),
        )
    audit.emit_event(
        conn, "application", aid,
        "application.handoff_manual",
        {
            "novnc_url": novnc_url,
            "session_id": session_id,
        },
    )


def load_active_handoff_session_id(conn, application_id: str) -> str | None:
    """session_id последнего handoff для заявки (audit-событие
    application.handoff_manual), ТОЛЬКО если хендофф ещё активен, то есть заявка
    стоит в state='fill_blocked' с current_blocker='handoff_manual'.
    None — если хендофф не запускался, ИЛИ заявка уже вышла из handoff_manual
    (resume уже успешно завершился, либо заявка обработана иначе) — в обоих
    случаях вызывающий (resume_fill) честно ответит no_active_session вместо
    вводящего в заблуждение session_expired."""
    aid = uuid.UUID(str(application_id))
    with conn.cursor() as cur:
        cur.execute(
            "select e.payload_json->>'session_id' from event e "
            "join application a on a.application_id = e.entity_id "
            "where e.entity_id=%s and e.event_type='application.handoff_manual' "
            "and a.state='fill_blocked' and a.current_blocker='handoff_manual' "
            "order by e.created_at desc limit 1",
            (aid,),
        )
        row = cur.fetchone()
    return row[0] if row else None
