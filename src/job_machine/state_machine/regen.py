"""Контролируемый reopen заявки для перегенерации резюме — через state-машину (§3).

Легальный переход FILL_BLOCKED/PACKAGE_READY/SUBMIT_BLOCKED -> NEEDS_PACKAGE + сброс
resume_artifact_id/current_blocker, чтобы RG-12 и Package пересобрали заявку с
адаптированным резюме. Старое approval инвалидируется сменой payload_hash при
repackage (гарды submit-пути) — SUBMIT_BLOCKED идёт по тому же пути, а не отдельным
submit-only retry: блокер мог быть вызван не только транзиентной инфраструктурой
(stale job-browser deploy, 2026-07-19), а и устаревшим resume/answers, так что полный
re-package безопаснее частичного ретрая."""
import uuid

from job_machine import audit
from job_machine.state_machine.controller import attempt_transition
from job_machine.state_machine.states import ApplicationState as A

# AGENT_FILL_PENDING реопенабельно наравне с fill_blocked: это ПЕРЕХОДНОЕ состояние
# ожидания агента, а не исход. Пока его здесь не было, заявку с агентской сессией
# (в т.ч. уже мёртвой после рестарта воркера) нельзя было вернуть в очередь ничем,
# кроме ожидания таймаут-свипа — обнаружено на живом прогоне 2026-08-07. Страницу
# освобождает тот же свип, он ищет по agent_fill_session_id, а не по состоянию,
# поэтому reopen её не осиротит.
_REOPENABLE = {A.FILL_BLOCKED.value, A.PACKAGE_READY.value, A.SUBMIT_BLOCKED.value,
               A.AGENT_FILL_PENDING.value}

_HANDOFF_BLOCKER = "handoff_manual"


def _is_active_handoff(state, current_blocker) -> bool:
    """Живой ручной хендофф (CAPTCHA/MFA): каноничная пара
    state='fill_blocked' + current_blocker='handoff_manual' (mcp/handoff_store.py,
    миграция 0021 убрала отдельное state='handoff_manual'). Общий предикат для
    reopen_for_regen И refile_application — обе функции обязаны трактовать эту
    комбинацию одинаково. Если разойдутся: reopen_for_regen говорит "не
    реопенабельно, иди в refile", а refile_application говорит "реопенабельно,
    иди в reopen" — тупик без пути восстановления через API (регрессия, найденная
    ревью 2026-08-05)."""
    return state == A.FILL_BLOCKED.value and current_blocker == _HANDOFF_BLOCKER


def _reset_resume_and_emit_reopened(conn, aid, current) -> dict:
    with conn.cursor() as cur:
        cur.execute("update application set resume_artifact_id=NULL, current_blocker=NULL, "
                    "updated_at=now() where application_id=%s", (aid,))
    audit.emit_event(conn, "application", aid, "application.reopened",
                     {"prev_state": current})
    conn.commit()
    return {"ok": True, "application_id": str(aid), "prev_state": current}


def reopen_for_regen(conn, application_id: str) -> dict:
    aid = uuid.UUID(str(application_id))
    with conn.cursor() as cur:
        cur.execute("select state, resume_artifact_id, current_blocker from application "
                    "where application_id=%s", (aid,))
        row = cur.fetchone()
    if row is None:
        return {"ok": False, "error": "no such application"}
    current, resume_artifact_id, current_blocker = row

    if current == A.NEEDS_PACKAGE.value:
        # Уже в needs_package: сброс resume_artifact_id — no-op перехода needs_package
        # -> needs_package в графе нет (и не нужен), но стухший артефакт всё равно надо
        # снять, иначе run_package упакует заявку по старому резюме (баг daria-b 23 заявки).
        # Ветка сознательно в обход attempt_transition/GUARDS (для needs_package их сейчас
        # нет вовсе — transitions.py); если когда-нибудь появится guard на переход *->
        # needs_package, которому нужно применяться и к этому refresh-пути, его придётся
        # прогнать здесь явно — тут он не подхватится автоматически.
        if resume_artifact_id is None:
            # current_blocker НЕ трогаем: единственное реалистичное значение здесь —
            # triage_skip (triage/store.py apply_verdict, флип apply->skip) — намеренная
            # пометка "не паковать", а не забытый блокер; очистка вернула бы в очередь
            # пакетирования заявку, которую владелец уже решил пропустить. Отдаём его
            # в ответе, чтобы вызывающий (агент) не принял no_op за "полностью здорова".
            return {"ok": True, "application_id": str(aid), "prev_state": current,
                    "no_op": True, "current_blocker": current_blocker}
        return _reset_resume_and_emit_reopened(conn, aid, current)

    if _is_active_handoff(current, current_blocker):
        # fill_blocked САМ ПО СЕБЕ реопенабелен безусловно — но активный хендофф значит,
        # что человек прямо сейчас сидит в живой браузерной сессии на капче/MFA; тихий
        # reopen сбросил бы current_blocker/resume_artifact_id и осиротил бы эту сессию
        # (resume_fill её больше не найдёт). Отказ должен быть раньше общей ветки
        # _REOPENABLE, иначе она пропустит fill_blocked не глядя на блокер.
        return {"ok": False, "error": f"state {current} with active handoff not reopenable",
                "reopen_policy": "manual_fail_and_refile"}

    if current not in _REOPENABLE:
        # Состояния вне _REOPENABLE делятся на: легальные в ApplicationState, но без
        # обратного ребра в needs_package (pre_submit_ready/awaiting_approval/approved/
        # submitted — реально исполненный или ожидающий явного решения шаг воронки,
        # откатывать резюме через этот путь нельзя без потери прогресса), и легаси-значения
        # вовсе вне enum (напр. handoff_manual как отдельный state — до миграции 0021
        # ставился напрямую SQL; сейчас такой строки в БД быть не должно, констрейнт
        # application_state_canonical_chk её отвергнет, но старые тестовые/архивные
        # данные могли её содержать). Обоим нужна ручная разборка, а не тихий "not
        # reopenable" без классификации — политика fail+refile (заявка помечается
        # failed и переподаётся заново) пока backlog.
        return {"ok": False, "error": f"state {current} not reopenable",
                "reopen_policy": "manual_fail_and_refile"}

    def _writer(entity_type, entity_id, *, state=None, current_blocker=None):
        sets, params = [], []
        if state is not None:
            sets.append("state=%s")
            params.append(state.value if hasattr(state, "value") else state)
        sets.append("current_blocker=%s")
        params.append(current_blocker)
        sets.append("updated_at=now()")
        params.append(uuid.UUID(str(entity_id)))
        with conn.cursor() as cur:
            cur.execute(
                f"update application set {', '.join(sets)} where application_id=%s", params)

    def _emit(entity_type, entity_id, event_type, payload, trace_id=None):
        audit.emit_event(conn, entity_type, uuid.UUID(str(entity_id)), event_type,
                         payload, trace_id)

    result = attempt_transition(
        "application", str(aid), A(current), A.NEEDS_PACKAGE, None,
        state_writer=_writer, audit_emitter=_emit)
    if not result.ok:
        return {"ok": False, "error": "transition blocked"}

    return _reset_resume_and_emit_reopened(conn, aid, current)


def refile_application(conn, application_id: str) -> dict:
    """Fail+refile: заявка в состоянии, откуда reopen_for_regen структурно
    невозможен — легаси handoff_manual вне ApplicationState enum (исторически, до
    миграции 0021), ЛИБО активный ручной хендофф (state='fill_blocked' +
    current_blocker='handoff_manual', см. _is_active_handoff) — reopen_for_regen
    сознательно отказывает и на этой паре, чтобы не осиротить живую браузерную
    сессию тихим сбросом резюме; refile — единственный путь восстановления для
    такой заявки. submit_blocked и обычный fill_blocked/package_ready сюда НЕ
    относятся — task_e70e18b1 сделал их реопенабельными через обычный
    reopen_for_regen, см. _REOPENABLE. Заявка помечается
    'failed' (сохраняется как история — не удаляется) и переподаётся заново:
    новая заявка на ТУ ЖЕ (candidate_id, vacancy_id) с состояния needs_package.

    Verdict/claims_version переносятся из старой заявки без повторного триажа —
    triage_result уже в БД и переиспользуется по join (candidate_id, vacancy_id),
    не по application_id (см. mcp/store.py::load_fit) — новая заявка сразу видит
    тот же fit-разбор. resume_artifact_id и current_blocker НЕ переносятся: новый
    пакет должен собраться с нуля через обычный run_package/run_fill конвейер.

    Отказывает, если для этой пары (candidate_id, vacancy_id) уже есть другая
    НЕ-failed заявка — иначе дубли активных заявок на одну вакансию."""
    aid = uuid.UUID(str(application_id))
    with conn.cursor() as cur:
        cur.execute(
            "select state, current_blocker, vacancy_id, candidate_id, verdict, "
            "claims_version from application where application_id=%s", (aid,))
        row = cur.fetchone()
    if row is None:
        return {"ok": False, "error": "no such application"}
    current, current_blocker, vacancy_id, candidate_id, verdict, claims_version = row

    active_handoff = _is_active_handoff(current, current_blocker)
    if not active_handoff and (current in _REOPENABLE or current == A.NEEDS_PACKAGE.value):
        return {"ok": False,
                "error": f"state {current} is reopenable via reopen_for_regen, use that instead"}

    with conn.cursor() as cur:
        cur.execute(
            "select application_id from application "
            "where candidate_id=%s and vacancy_id=%s and application_id!=%s and state!=%s",
            (candidate_id, vacancy_id, aid, A.FAILED.value))
        existing = cur.fetchone()
    if existing is not None:
        return {"ok": False,
                "error": "another active application already exists for this vacancy+candidate",
                "existing_application_id": str(existing[0])}

    with conn.cursor() as cur:
        cur.execute("update application set state=%s, updated_at=now() "
                    "where application_id=%s", (A.FAILED.value, aid))
    audit.emit_event(conn, "application", aid, "application.failed",
                     {"prev_state": current, "reason": "refiled"})

    with conn.cursor() as cur:
        cur.execute(
            "insert into application (vacancy_id, candidate_id, verdict, package_status, "
            "current_blocker, state, claims_version) "
            "values (%s,%s,%s,'none',NULL,%s,%s) returning application_id",
            (vacancy_id, candidate_id, verdict, A.NEEDS_PACKAGE.value, claims_version))
        new_aid = cur.fetchone()[0]
    audit.emit_event(conn, "application", new_aid, "application.refiled",
                     {"prev_application_id": str(aid), "prev_state": current})
    conn.commit()
    return {"ok": True, "old_application_id": str(aid), "new_application_id": str(new_aid),
            "state": A.NEEDS_PACKAGE.value}
