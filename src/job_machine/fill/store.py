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


def load_agent_package(conn, application_id) -> dict | None:
    with conn.cursor() as cur:
        cur.execute(
            "select a.agent_fill_session_id,a.payload_hash,r.path_or_uri,r.content_hash "
            "from application a join artifact r on r.application_id=a.application_id "
            "where a.application_id=%s and a.state='agent_fill_pending' "
            "and r.artifact_type='manifest' order by r.created_at desc limit 1",
            (application_id,))
        row = cur.fetchone()
    return dict(zip(('session_id','payload_hash','path','content_hash'), row)) if row else None


def lock_fillable(conn, application_id) -> bool:
    """Own the fill transition before touching a page; skip concurrent owners."""
    with conn.cursor() as cur:
        cur.execute(
            "select application_id from application where application_id=%s "
            "and agent_fill_session_id is null "
            "and (state='package_ready' or (state='fill_blocked' and current_blocker='handoff_manual')) "
            "for update skip locked", (application_id,))
        return cur.fetchone() is not None


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


def record_agent_fill_pending(conn, application_id, session_id, page_url,
                              unmatched, filled_fields=(), resume_attached=False) -> bool:
    """Код не сопоставил часть required-полей → страница передаётся агенту.

    В отличие от record_fill_blocked это НЕ терминальный стоп: current_blocker
    остаётся пустым, сессия браузера продолжает жить, заявка ждёт агента.

    filled_fields/resume_attached — что детерминированный проход уже сделал на этой
    странице до передачи. Нужны в аудите, чтобы по событию было видно границу между
    работой кода и работой агента, а не только остаток.
    """
    aid = uuid.UUID(str(application_id))
    with conn.cursor() as cur:
        cur.execute(
            "update application set state='agent_fill_pending', current_blocker=null, "
            "agent_fill_session_id=%s, agent_fill_started_at=now(), updated_at=now() "
            "where application_id=%s and agent_fill_session_id is null "
            "and (state='package_ready' or (state='fill_blocked' and current_blocker='handoff_manual'))",
            (session_id, aid))
        if cur.rowcount != 1:
            return False
    audit.emit_event(conn, "application", aid, "application.agent_fill_pending", {
        "session_id": session_id, "page_url": page_url, "unmatched": unmatched,
        "filled_fields": list(filled_fields), "resume_attached": bool(resume_attached),
    })
    return True


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


def pull_stale_agent_fills(conn, timeout_minutes: int) -> list[dict]:
    """Заявки, держащие браузерную сессию дольше timeout_minutes — страницы надо вернуть.

    Критерий — наличие session_id, а НЕ состояние. Заявку могли увести из
    agent_fill_pending мимо агента (refile_application помечает её failed и
    порождает дубликат), и тогда фильтр по состоянию оставил бы retained-страницу
    жить вечно: обычный dispose её не закрывает, а sweep_orphaned_contexts не видит
    — она числится в реестре сессий. Так и копятся контексты, положившие хост
    2026-07-06.
    """
    with conn.cursor() as cur:
        cur.execute(
            "select application_id, state, agent_fill_session_id from application "
            "where agent_fill_session_id is not null "
            "  and agent_fill_started_at < now() - make_interval(mins => %s)",
            (timeout_minutes,))
        rows = cur.fetchall()
    return [{"application_id": r[0], "state": r[1], "session_id": r[2]} for r in rows]


def clear_agent_fill_session(conn, application_id) -> None:
    """Обнулить agent_fill_session_id/agent_fill_started_at, чтобы свип не подбирал
    одну и ту же заявку каждый прогон."""
    aid = uuid.UUID(str(application_id))
    with conn.cursor() as cur:
        cur.execute(
            "update application set agent_fill_session_id=null, "
            "agent_fill_started_at=null, updated_at=now() where application_id=%s", (aid,))


def lock_stale_agent_fill(conn, row, timeout_minutes: int) -> bool:
    """Recheck the snapshot under row lock; submit claims must win or wait.

    Unknown/in-progress submissions remain untouched for reconciliation.
    Caller keeps the lock through release and commits (or rolls back on error).
    """
    with conn.cursor() as cur:
        cur.execute(
            "select application_id from application where application_id=%s "
            "and state=%s and agent_fill_session_id=%s "
            "and state in ('agent_fill_pending','pre_submit_ready','approved','failed','fill_blocked',"
            "'needs_package','package_ready') "
            "and agent_fill_started_at < now() - make_interval(mins => %s) "
            "for update skip locked",
            (row['application_id'], row['state'], row['session_id'], timeout_minutes))
        return cur.fetchone() is not None


def record_guard_block(conn, application_id, guard_result) -> None:
    """STOP fill-гарда: ставим fill_blocked + current_blocker=guard_name, пишем guard-событие."""
    aid = uuid.UUID(str(application_id))
    with conn.cursor() as cur:
        cur.execute(
            "update application set state='fill_blocked', fill_status='blocked', "
            "current_blocker=%s, updated_at=now() where application_id=%s",
            (guard_result.guard_name, aid))
    audit.emit_guard_event(conn, "application", aid, guard_result)
