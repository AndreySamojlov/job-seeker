"""DB-слой fill-воркера: выбор fillable-заявок, чтение manifest, запись состояний + audit.

Приватность: события несут имена полей, пути, hash — НИКОГДА сырые значения ответов.
"""

import uuid

from job_machine import audit
from job_machine.package.models import PackageManifest


def pull_fillable(conn, limit: int, candidate_id: str | None = None) -> list[dict]:
    """Заявки к заполнению: state='package_ready' И без блокера. Для каждой — её артефакты,
    резюме (path + раскрытый content_hash), путь manifest, наличие approval_summary, ats_family.

    candidate_id — если задан, fill-очередь скоупится этим кандидатом (симметрично
    pull_needs_package); иначе глобальный свип (обратная совместимость с n8n /fill/run)."""
    scope = ""
    params: list = []
    if candidate_id is not None:
        scope = "and a.candidate_id = %s "
        params.append(candidate_id)
    params.append(limit)
    with conn.cursor() as cur:
        cur.execute(
            "select a.application_id, a.vacancy_id, a.resume_artifact_id, v.ats_family "
            "from application a join vacancy v on v.vacancy_id = a.vacancy_id "
            "where a.state='package_ready' and a.current_blocker is null "
            f"{scope}"
            "order by a.created_at limit %s",
            tuple(params),
        )
        heads = cur.fetchall()
    return [_assemble_row(conn, aid, vid, ats_family, resume_artifact_id)
            for aid, vid, resume_artifact_id, ats_family in heads]


def _assemble_row(conn, application_id, vacancy_id, ats_family, resume_artifact_id) -> dict:
    """Собрать resume/manifest/artifacts для ОДНОЙ заявки (общее для pull_fillable
    и load_fillable_row_by_id). order by created_at desc: reopen+repackage добавляет
    НОВУЮ artifact-строку рядом со старой — без сортировки manifest_path мог
    указывать на устаревший (уже недействительный) путь."""
    with conn.cursor() as cur:
        cur.execute(
            "select artifact_id, artifact_type, path_or_uri, content_hash "
            "from artifact where application_id=%s order by created_at desc",
            (application_id,))
        arts = cur.fetchall()
    summary_artifacts = [{"artifact_type": t} for (_, t, _, _) in arts]
    manifest_path = next((p for (_, t, p, _) in arts if t == "manifest"), None)
    resume = None
    for (art_id, t, p, h) in arts:
        if art_id == resume_artifact_id or t == "resume":
            resume = {"path": p, "content_hash": h}
            break
    return {
        "application_id": str(application_id),
        "vacancy_id": str(vacancy_id),
        "ats_family": ats_family,
        "manifest_path": manifest_path,
        "resume": resume,
        "summary_artifacts": summary_artifacts,
    }


def load_fillable_row_by_id(conn, application_id: str) -> dict | None:
    """Та же сборка, что и pull_fillable, но для ОДНОЙ заявки по id, без фильтра
    state='package_ready' — используется resume_after_handoff, где заявка уже
    в state='fill_blocked' с current_blocker='handoff_manual'. None, если заявки нет."""
    with conn.cursor() as cur:
        cur.execute(
            "select a.application_id, a.vacancy_id, a.resume_artifact_id, v.ats_family "
            "from application a join vacancy v on v.vacancy_id = a.vacancy_id "
            "where a.application_id = %s",
            (application_id,),
        )
        head = cur.fetchone()
    if head is None:
        return None
    aid, vid, resume_artifact_id, ats_family = head
    return _assemble_row(conn, aid, vid, ats_family, resume_artifact_id)


def load_manifest(path: str) -> PackageManifest:
    """Прочитать manifest.json пакета в PackageManifest (источник disclosed answers/URL)."""
    with open(path, encoding="utf-8") as fh:
        return PackageManifest.model_validate_json(fh.read())


def record_pre_submit_ready(conn, application_id, filled_fields, resume_attached,
                            screenshot_path) -> None:
    aid = uuid.UUID(str(application_id))
    with conn.cursor() as cur:
        cur.execute(
            "update application set state='pre_submit_ready', fill_status='pre_submit_ready', "
            "current_blocker=null, updated_at=now() where application_id=%s", (aid,))
    audit.emit_event(conn, "application", aid, "application.pre_submit_ready", {
        "filled_fields": list(filled_fields),
        "resume_attached": bool(resume_attached),
        "screenshot_path": screenshot_path,
    })


def record_fill_blocked(conn, application_id, blocker, detail) -> None:
    aid = uuid.UUID(str(application_id))
    with conn.cursor() as cur:
        cur.execute(
            "update application set state='fill_blocked', fill_status='blocked', "
            "current_blocker=%s, updated_at=now() where application_id=%s", (blocker, aid))
    audit.emit_event(conn, "application", aid, "application.fill_blocked", {
        "blocker": blocker, "detail": detail,
    })


def record_destination_redirect(conn, application_id, vacancy_id,
                                source_url: str, final_url: str) -> None:
    """Редирект на ДРУГОЙ пост: fill_blocked + сигнал requisition-дедупа на vacancy.
    Форма чужого поста не заполняется (аудит 02.07: 16/35 ушли не туда)."""
    record_fill_blocked(conn, application_id, "destination_redirect",
                        {"source_url": source_url, "final_url": final_url})
    audit.emit_event(conn, "vacancy", uuid.UUID(str(vacancy_id)),
                     "vacancy.requisition_duplicate", {
                         "application_id": str(application_id),
                         "source_url": source_url,
                         "final_url": final_url,
                     })


def record_destination_resolved(conn, application_id, source_url: str, final_url: str,
                                manifest, artifact_descs: list[dict]) -> None:
    """Ребинд payload на фактический URL: append новых артефактов, обновление
    payload_hash/final_apply_url + событие. Старые artifact-строки не правятся."""
    aid = uuid.UUID(str(application_id))
    with conn.cursor() as cur:
        cur.execute("select payload_hash from application where application_id=%s", (aid,))
        row = cur.fetchone()
        old_hash = row[0] if row else None
        for d in artifact_descs:
            cur.execute(
                "insert into artifact (application_id, artifact_type, path_or_uri, "
                "content_hash) values (%s,%s,%s,%s)",
                (aid, d["artifact_type"], d["path"], d["content_hash"]))
        cur.execute(
            "update application set payload_hash=%s, final_apply_url=%s, "
            "updated_at=now() where application_id=%s",
            (manifest.payload_hash, final_url, aid))
    audit.emit_event(conn, "application", aid, "application.destination_resolved", {
        "old_url": source_url, "final_apply_url": final_url,
        "old_payload_hash": old_hash, "new_payload_hash": manifest.payload_hash,
    })


def record_final_apply_url(conn, application_id, final_url: str) -> None:
    """Финальный URL совпал с destination строково — фиксируем без ребинда."""
    with conn.cursor() as cur:
        cur.execute("update application set final_apply_url=%s, updated_at=now() "
                    "where application_id=%s", (final_url, uuid.UUID(str(application_id))))


def record_guard_block(conn, application_id, guard_result) -> None:
    """STOP fill-гарда: ставим fill_blocked + current_blocker=guard_name, пишем guard-событие."""
    aid = uuid.UUID(str(application_id))
    with conn.cursor() as cur:
        cur.execute(
            "update application set state='fill_blocked', fill_status='blocked', "
            "current_blocker=%s, updated_at=now() where application_id=%s",
            (guard_result.guard_name, aid))
    audit.emit_guard_event(conn, "application", aid, guard_result)
