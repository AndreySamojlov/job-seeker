"""Чистые логические функции MCP-инструментов (conn/browser инъектятся).

Каждая функция принимает уже открытое соединение/клиент — это делает их юнит-
тестируемыми с FakeConn (см. tests/mcp/). FastMCP-обёртки (server.py) подставляют
реальные connect()/SubmitBrowserClient.
"""
import logging
import re
import uuid

import httpx

from job_machine.mcp import store, funnel, handoff_store, agent_fill_store
from job_machine.mcp import store as mcp_store
from job_machine.approval import service as approval_service
from job_machine.approval import store as approval_store
from job_machine.runtime import control as runtime_control
from job_machine.pipeline import runner as pipeline_runner
from job_machine.discovery import service as discovery_service
from job_machine.discovery.sources import (
    BROWSER_BACKED_ATS, SourceSpec, load_sources, paginate_sources,
)
from job_machine.telegram_sourcing import store as telegram_store
from job_machine.package import service as package_service
from job_machine.package import store as package_store
from job_machine.package.models import AnswerRecord
from job_machine.ats import greenhouse_questions
from job_machine.state_machine import regen

log = logging.getLogger(__name__)


def get_search_profile(conn, candidate_id: str) -> dict:
    """Вернуть цели поиска кандидата для сверки в меню."""
    return store.load_search_profile(conn, candidate_id)


def update_search_profile(conn, patch: dict, candidate_id: str) -> dict:
    """Применить правки целей кандидата, вернуть актуальные."""
    store.update_search_profile(conn, patch, candidate_id)
    conn.commit()
    return store.load_search_profile(conn, candidate_id)


def list_ready(conn, candidate_id: str, limit: int = 20) -> list[dict]:
    """Очередь готовых к одобрению заявок кандидата (узкий срез, без DOM/vault — §16)."""
    return store.query_ready_queue(conn, candidate_id, limit)


def list_candidates(conn) -> list[dict]:
    """Активные кандидаты для выбора в начале сессии."""
    return store.list_candidates(conn)


def get_submit_control(conn) -> dict:
    """Текущее состояние рубильника подачи (§3 fail-closed): включён ли submit,
    кто и когда его последний раз переключал. Единственный способ владельцу
    узнать состояние без ручного SQL — до этого среза его нельзя было ни
    прочитать, ни переключить через MCP вовсе."""
    return runtime_control.read_submit_control(conn)


def set_submit_control(conn, enabled: bool, actor: str) -> dict:
    """Включить/выключить рубильник подачи. actor обязателен и попадает в
    updated_by (аудит-трейл, кто именно включил submit). Авторизация вызывающего
    происходит выше по стеку (владелец подтверждает действие в чате) — здесь
    только запись."""
    changed = runtime_control.set_submit_enabled(conn, enabled, actor)
    conn.commit()
    status = runtime_control.read_submit_control(conn)
    return {"ok": changed, **status}


# Текст диагностики, когда job-submit недоступен (мёртвый туннель/воркер). На submit-
# пути критично: владелец должен ОДНОЗНАЧНО понимать, что заявка НЕ подана (§3 fail-closed).
_WORKER_DOWN = ("job-submit воркер недоступен (SUBMIT_WORKER_URL). Заявка НЕ подана. "
                "Подними туннель: tunnelctl start job-submit (C:\\Users\\samoj\\.claude\\tools\\"
                "tunnel-daemon), затем повтори. Голый ssh -L заблокирован хуком.")


def get_application(submit_worker, application_id: str) -> dict:
    """Детали + disclosed summary заявки для презентации перед одобрением.

    Делегируется job-submit воркеру: disclosed-summary-артефакт лежит на /data, которого
    у локального MCP нет (вариант A task_7b246bd8). Воркер читает БД + /data и отдаёт dict.
    """
    try:
        return submit_worker.get_application_detail(application_id)
    except httpx.HTTPError as exc:
        return {"application_id": application_id, "error": "submit_worker_unreachable",
                "detail": str(exc), "summary_md": ""}


_FIT_VECTOR_LABELS = {
    "requirements": "Требования", "hands_on": "Практика", "domain": "Домен",
    "stack": "Стек", "role_family": "Роль", "seniority": "Сеньорити",
    "geo_mode": "Гео",
}
# Строки fit-1 несут другие ключи — рендерим их старыми метками, чтобы разбор
# накопленных заявок не падал после перехода на fit-2.
_FIT_AXIS_LABELS = {"requirements": "Требования", "role_family": "Роль",
                    "seniority": "Сеньорити", "geo": "Гео"}


def _render_fit_md(fit: dict) -> str:
    if not fit:
        return "Соответствие: скор не рассчитан."
    # Фаза 1. Заблокированной заявке нечего показывать про баллы — у неё их нет;
    # владельцу нужна причина отказа, а не пустая таблица векторов.
    elig = fit.get("eligibility") or {}
    if elig.get("blocked"):
        return "\n".join(["**Допуск: заблокировано**", "",
                          f"- Категория: {elig.get('category')}",
                          f"- Обоснование: {elig.get('reason')}"])

    # Скор мог не считаться вовсе (обнулён до переизвлечения фактов, либо строка ещё
    # не проходила фазу пригодности). Честно сказать это, а не печатать None/100.
    if fit.get("fit_score") is None or fit.get("fit_band") is None:
        return "Соответствие: скор не рассчитан."

    bd = fit.get("fit_breakdown") or {}
    vectors, labels = bd.get("vectors"), _FIT_VECTOR_LABELS
    if vectors is None:                       # легаси-строка fit-1
        vectors, labels = bd.get("axes", {}), _FIT_AXIS_LABELS
    lines = [f"**Соответствие: {fit['fit_band']} ({fit['fit_score']}/100)**", "",
             "Векторы:"]
    for k, lab in labels.items():
        v = vectors.get(k)
        lines.append(f"- {lab}: {'—' if v is None else v}")
    capped = bd.get("capped_by") or []
    if capped:
        lines += ["", f"Потолок бэнда (не выше C) из-за: {', '.join(capped)}"]
    flags = bd.get("flags") or []
    if flags:
        lines += ["", "Флаги: " + ", ".join(flags)]
    if elig.get("unknowns"):
        lines += ["", "Неизвестности допуска (раскрыты для одобрения):"]
        lines += [f"- {u}" for u in elig["unknowns"]]
    if fit.get("material_unknowns"):
        lines += ["", "Материальные неизвестные (раскрыты для одобрения):"]
        lines += [f"- {u}" for u in fit["material_unknowns"]]
    if fit.get("overclaim_risks"):
        lines += ["", "Риски переоценки (раскрыты для одобрения):"]
        lines += [f"- {o}" for o in fit["overclaim_risks"]]
    return "\n".join(lines)


def get_application_fit(conn, application_id: str) -> dict:
    """Живой разбор соответствия заявки из triage_result (для показа при одобрении).

    Не трогает disclosed-summary артефакт: читает БД напрямую, доступен ещё до сборки
    пакета. Скор ИНФОРМАТИВНЫЙ — не гейт (§3): submit по-прежнему требует явного одобрения.
    """
    fit = mcp_store.load_fit(conn, application_id)
    return {"application_id": str(application_id), "fit_md": _render_fit_md(fit), **fit}


def request_approval(conn, application_id: str) -> dict:
    """Сминтить approval-токен, привязанный к payload_hash заявки (статус 'pending')."""
    with conn.cursor() as cur:
        cur.execute("select payload_hash from application where application_id=%s",
                    (application_id,))
        row = cur.fetchone()
    if row is None or not row[0]:
        return {"error": "no payload_hash for application", "application_id": application_id}
    payload_hash = row[0]
    approval_id = approval_service.request_approval(conn, application_id, payload_hash)
    conn.commit()
    return {"approval_id": approval_id, "application_id": application_id,
            "payload_hash": payload_hash}


def approve_application(conn, application_id: str) -> dict:
    """Перевести pending-approval в 'approved' (после явного одобрения в меню)."""
    ok = approval_store.approve(conn, application_id)
    conn.commit()
    return {"approved": bool(ok), "application_id": application_id}


def submit_application(conn, submit_worker, application_id: str,
                       csv_path: str = "audit/submissions.csv") -> dict:
    """Submit одной одобренной заявки под токеном (трипл-gate). Вернуть confirmation.

    Делегируется job-submit воркеру (вариант A task_7b246bd8): submit-логика читает
    manifest/резюме с /data и ходит в job-browser — этого нет у локального MCP. Трипл-gate
    (§3) исполняется в воркере; confirmation читается из БД (доступна локально по туннелю).
    """
    try:
        summary = submit_worker.submit_one(application_id)
    except httpx.HTTPError as exc:
        # Fail-closed: submit не состоялся. Явная доменная ошибка вместо сырого трейса —
        # владелец должен видеть «не подано», а не гадать, прошёл ли необратимый submit.
        return {
            "application_id": application_id,
            "pulled": 0, "submitted": 0, "blocked": 0, "errors": 1,
            "status": "submit_worker_unreachable",
            "confirmation_url": None,
            "funnel_recorded": False,
            "error": _WORKER_DOWN, "detail": str(exc),
        }
    conf = store.load_submit_confirmation(conn, application_id)
    funnel_recorded = False
    if summary.submitted:
        # Автозапись audit-строки из БД по факту submit; сбой CSV не маскирует
        # состоявшийся submit (best-effort, флаг в ответе).
        try:
            funnel.sync_submissions(conn, csv_path, application_id=application_id)
            funnel_recorded = True
        except Exception:  # noqa: BLE001
            funnel_recorded = False
    return {
        "application_id": application_id,
        "pulled": summary.pulled,
        "submitted": summary.submitted,
        "blocked": summary.blocked,
        "errors": summary.errors,
        "status": conf["status"],
        "confirmation_url": conf["confirmation_url"],
        "funnel_recorded": funnel_recorded,
    }


def record_outcome(conn, application_id: str,
                   csv_path: str = "audit/submissions.csv") -> dict:
    """Fail-closed запись в audit-CSV: строка деривируется ИЗ БД (submitted_at — из
    события application.submitted); неизвестный/неподанный id → ошибка без записи.
    Идемпотентен (повтор по уже записанному id — не дубль)."""
    try:
        uuid.UUID(str(application_id))
    except (ValueError, TypeError, AttributeError):
        return {"recorded": False, "application_id": str(application_id),
                "error": "invalid application_id (not a UUID)"}
    result = funnel.sync_submissions(conn, csv_path, application_id=application_id)
    if result["matched"] == 0:
        return {"recorded": False, "application_id": str(application_id),
                "error": "no application.submitted event for this id — нечего записывать"}
    if result["invalid"]:
        return {"recorded": False, "application_id": str(application_id),
                "error": "submitted row lacks required audit fields (url/submitted_at)"}
    return {"recorded": True, "application_id": str(application_id),
            "already_recorded": result["appended"] == 0}


def funnel_stats(conn, candidate_id: str) -> dict:
    """Метрики воронки кандидата для выводов агента (узкий агрегат, не дамп)."""
    return store.count_by_state(conn, candidate_id)


def handoff_browser(conn, browser, application_id: str) -> dict:
    """Передать живую браузерную сессию человеку для ручного взаимодействия.

    Используется когда конвейер упёрся в CAPTCHA/MFA/нестандартный шаг (§3 ТЗ).
    Создаёт persist-сессию, навигирует к URL формы, отображает через noVNC.

    ИНВАРИАНТ (§3/§4): эта функция физически НЕ вызывает submit. Передача управления
    человеку — не обход гарда, а корректный стоп конвейера.

    Возвращает dict с ok/session_id/novnc_url/status/instructions.
    """
    url = handoff_store.load_destination_url(conn, application_id)
    if not url:
        return {
            "ok": False,
            "error": "destination URL not found",
            "application_id": application_id,
        }

    old_sid = handoff_store.load_active_handoff_session_id(conn, application_id)
    if old_sid is not None:
        try:
            browser.release(old_sid)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 404:
                raise
            log.warning("release старой handoff-сессии %s для заявки %s: уже не существует (404)",
                       old_sid, application_id)

    result = browser.handoff(url)
    handoff_store.record_handoff_manual(
        conn, application_id,
        novnc_url=result.novnc_url,
        session_id=result.session_id,
    )
    conn.commit()

    if result.novnc_url:
        instructions = (
            f"Откройте noVNC: {result.novnc_url}\n"
            f"Браузер открыт на: {url}\n"
            "Выполните CAPTCHA/MFA вручную, затем вызовите handoff release."
        )
    else:
        instructions = (
            f"NOVNC_BASE_URL не задан. Порт 6080 сейчас НЕ опубликован job-browser на хост "
            f"lab-do (в отличие от 8090/8091/8092) — туннелем недостижим, ни ssh -L, ни tunnelctl. "
            f"Нужен compose-фикс (публикация 127.0.0.1:6080), потом запись в registry.toml "
            f"tunnel-daemon и tunnelctl start job-novnc.\n"
            f"Браузер открыт на: {url}\n"
            "Выполните CAPTCHA/MFA вручную, затем вызовите handoff release."
        )

    return {
        "ok": True,
        "session_id": result.session_id,
        "novnc_url": result.novnc_url,
        "status": result.status,
        "instructions": instructions,
    }


def resume_fill(conn, fill_worker, application_id: str) -> dict:
    """Продолжить fill ПОСЛЕ того, как владелец вручную прошёл CAPTCHA/MFA через
    handoff_browser — в ТОЙ ЖЕ browser-сессии (без повторной капчи).

    {"ok": False, "error": "no_active_session"} — handoff_browser для этой заявки
    не запускался (или сессия уже разрешилась). Иначе — результат
    fill_worker.resume_after_handoff (см. fill.service.resume_after_handoff)."""
    session_id = handoff_store.load_active_handoff_session_id(conn, application_id)
    if session_id is None:
        return {"ok": False, "error": "no_active_session"}
    return fill_worker.resume_after_handoff(application_id, session_id)


def agent_fill_start(conn, application_id: str, fill_worker) -> dict:
    """Выдать агенту живую страницу заявки для дозаполнения.

    Заявка ждёт агента в state='agent_fill_pending' (код не сопоставил часть
    required-полей, но браузерная сессия жива — fill/service.py уже сделал
    browser.retain). Отдаём агенту всё, что нужно, чтобы присоединиться к той
    же вкладке по CDP и дозаполнить честно, без вымысла.

    Читает состояние и проверенные значения пакета через fill worker.
    Этот вызов не нажимает submit; доступ через CDP сам по себе не ограничен.

    ok=False с error="not_agent_fill_pending" — заявка не в agent_fill_pending
    (или уже обработана: агент/владелец её закрыл раньше).
    """
    live = agent_fill_store.load_agent_fill(conn, application_id)
    if live is None:
        return {"ok": False, "error": "not_agent_fill_pending",
                "application_id": application_id}

    context = fill_worker.agent_context(application_id, live["session_id"])
    if not context.get("ok"):
        return context
    answers = context["answers"]
    instructions = (
        "Присоединись к CDP-эндпоинту браузер-воркера и выбери вкладку с page_url "
        f"({live['page_url']}). Дозаполни поля, перечисленные в unmatched, значениями "
        "ТОЛЬКО из answers — ничего не выдумывай, чего нет в answers, не заполняй. "
        "Новых вкладок не открывай. Финальную кнопку (submit) НЕ нажимай ни при каких "
        "условиях — это отдельный шаг, требующий одобрения владельца. По готовности "
        "заново инспектируй форму и вызови agent_fill_done с session_id и фактическим остатком "
        "несопоставленных полей (пустой список — если форма готова целиком). Если "
        "честно добить форму нельзя (недостающий факт, CAPTCHA, MFA, требуется "
        "создание аккаунта, таймаут) — вызови agent_fill_blocked с session_id и причиной."
    )
    return {
        "ok": True,
        "application_id": application_id,
        "session_id": live["session_id"],
        "page_url": live["page_url"],
        "unmatched": live["unmatched"],
        "answers": answers,
        "instructions": instructions,
    }


def agent_fill_done(conn, browser, application_id: str, inspect_unmatched,
                    session_id: str | None = None) -> dict:
    """Accept current-session results only after independent live form inspection.

    Retain the page for the separate approval/submit flow. Structural readiness
    does not prove that answers match facts or an approved package.
    """
    live = agent_fill_store.load_agent_fill(conn, application_id)
    if live is None:
        return {"ok": False, "error": "not_agent_fill_pending",
                "application_id": application_id}
    if not session_id or session_id != live["session_id"]:
        return {"ok": False, "error": "stale_session"}
    if inspect_unmatched:
        return {"ok": False, "error": "still_unmatched", "unmatched": inspect_unmatched}
    try:
        evidence = browser.readiness(session_id)
    except httpx.HTTPError:
        return {"ok": False, "error": "readiness_unavailable"}
    if not live.get("page_url") or evidence.get("url") != live["page_url"]:
        return {"ok": False, "error": "destination_changed"}
    if evidence.get("ready") is not True or evidence.get("blocker"):
        return {"ok": False, "error": "form_not_ready", "blocker": evidence.get("blocker")}
    if not agent_fill_store.record_agent_fill_done(conn, application_id, session_id):
        return {"ok": False, "error": "stale_session"}
    conn.commit()
    return {"ok": True, "status": "pre_submit_ready", "application_id": application_id,
            "session_id": session_id}


def agent_fill_blocked(conn, browser, application_id: str, reason: str,
                       session_id: str | None = None) -> dict:
    """Block only the current pending session; never release a replacement."""
    live = agent_fill_store.load_agent_fill(conn, application_id)
    if live is None:
        return {"ok": False, "error": "not_agent_fill_pending",
                "application_id": application_id}
    if not session_id or session_id != live["session_id"]:
        return {"ok": False, "error": "stale_session"}
    if reason not in {"missing_fact", "captcha", "mfa", "account_required", "timeout"}:
        return {"ok": False, "error": "invalid_reason"}
    if not agent_fill_store.record_agent_fill_blocked(conn, application_id, reason, session_id):
        return {"ok": False, "error": "stale_session"}
    conn.commit()
    cleanup_pending = False
    try:
        browser.release(session_id)
    except httpx.HTTPError as exc:
        cleanup_pending = not (isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 404)
    # Keep the session reference for idempotent sweep, including failed releases.
    return {"ok": True, "status": "fill_blocked", "reason": reason,
            "application_id": application_id, "cleanup_pending": cleanup_pending}


def run_pipeline(conn, greenhouse_client, fill_worker=None, package_worker=None,
                 boards=None, max_boards: int = 3, offset: int = 0, limit: int = 10,
                 base_dir: str = "applications",
                 candidate_id: str | None = None) -> dict:
    """Ограниченный последовательный прогон конвейера (early-stop на первой ошибке).

    Источники — config/sources.json (мульти-ATS). Для больших батчей вызывайте
    стадии по отдельности: run_discovery/run_verify/run_package/run_fill —
    так виден промежуточный прогресс и нет одного длинного blocking-вызова.

    package_worker — PackageWorkerClient (HTTP-делегирование, рекомендуется): MCP-
    контекст не имеет /data → package делегируется воркеру (тот пишет на разделяемый
    /data, читаемо job-fill). Без него — local package_service на base_dir (тесты/
    прямой запуск; на Windows пишет нечитаемые lab-do backslash-пути → broken_flow).

    candidate_id — скоуп package/fill стадий этим кандидатом (discovery/verify —
    общий пул по всем кандидатам, не скоупятся).
    """
    return pipeline_runner.run_pipeline(
        conn, greenhouse_client, fill_worker=fill_worker, package_worker=package_worker,
        boards=boards, max_boards=max_boards, offset=offset, limit=limit,
        base_dir=base_dir, candidate_id=candidate_id,
    )


def run_discovery(conn, max_boards: int = 3, offset: int = 0,
                  sources: list[SourceSpec] | None = None) -> dict:
    """Обойти срез [offset:offset+max_boards] источников из sources.json.

    ``sources`` — инъекция для тестов; в проде не передаётся (грузится sources.json).
    Дефолтная ветка (sources=None) исключает browser-backed ATS (hh) — у них свой
    отдельный, более редкий cron; явно переданный ``sources`` НЕ фильтруется —
    вызывающий получает ровно то, что запросил.
    Возвращает next_offset для продолжения обхода следующим вызовом (None —
    бордов больше не осталось).
    """
    specs = sources if sources is not None else [
        s for s in load_sources() if s.ats not in BROWSER_BACKED_ATS
    ]
    page, next_offset = paginate_sources(specs, max_boards, offset)
    summary = discovery_service.run_discovery_multi(conn, page)
    return {
        "boards_processed": len(page), "boards_total": len(specs),
        "next_offset": next_offset,
        "fetched": summary.fetched, "inserted": summary.inserted,
        "duplicates": summary.duplicates, "errors": summary.errors,
    }


def run_verify(conn, client, limit: int = 10) -> dict:
    """Проверить до `limit` discovered-вакансий на живость (per-ATS диспатч клиента)."""
    summary = discovery_service.run_verify(conn, client, limit)
    return {"checked": summary.checked, "verified": summary.verified,
            "stale": summary.stale, "transient": summary.transient}


def run_package(package_worker, limit: int = 10,
                candidate_id: str | None = None) -> dict:
    """Собрать пакеты для до `limit` needs_package-заявок через job-package воркер
    (HTTP; скоуп по candidate_id)."""
    built = package_worker.run_package_build(limit, candidate_id)
    return {"built": built}


def run_fill(fill_worker, limit: int = 10, candidate_id: str | None = None) -> dict:
    """Заполнить формы до `limit` заявок через job-fill воркер (HTTP; скоуп по candidate_id)."""
    result = fill_worker.run_fill(limit, candidate_id)
    return {"pulled": result.pulled, "pre_submit_ready": result.pre_submit_ready,
            "agent_fill_pending": result.agent_fill_pending,
            "blocked": result.blocked, "errors": result.errors}


_IDENTITY_FIELDS = {"first_name", "last_name", "preferred_name", "email", "phone",
                    "resume", "resume_text", "cover_letter", "cover_letter_text"}

# §3 fail-safe: поля-согласия/декларации НЕ принимаются как locked-ответы (иначе они
# попали бы в disclosed summary как обычный переданный ответ, маскируя согласие).
# Их ставит ТОЛЬКО человек в живом браузере (handoff). Триппвайр срабатывает по
# нормализованному тексту поля; work-auth/salary НЕ ловятся (это отвечаемые факты).
_CONSENT_TOKENS = ("consent", "privacy notice", "i agree", "terms and conditions",
                   "declaration", "acknowledge")


def _looks_like_consent(field: str) -> bool:
    n = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", (field or "").lower())).strip()
    return any(tok in n for tok in _CONSENT_TOKENS)


def set_application_answers(conn, application_id: str, answers: list[dict]) -> dict:
    """Сохранить per-application ответы (locked). Согласия/декларации ОТКЛОНЯЮТСЯ (§3):
    их проставляет человек в живом браузере, а не код. Возвращает saved + rejected."""
    accepted, rejected = [], []
    for a in answers:
        if _looks_like_consent(a["field"]):
            rejected.append(a["field"])
        else:
            accepted.append(AnswerRecord(field=a["field"], value=a["value"], state="locked"))
    if accepted:
        package_store.upsert_application_answers(conn, application_id, accepted)
        conn.commit()
    return {"saved": len(accepted), "rejected": rejected,
            "application_id": str(application_id)}


def regenerate_resume(conn, application_id: str) -> dict:
    """Безопасный reopen заявки для перегенерации адаптированного резюме.

    ok=True с no_op=True — заявка уже в needs_package и резюме уже сброшено
    (перегенерация не требуется); проверь current_blocker в ответе — заявка
    может быть намеренно исключена из пакетирования (напр. triage_skip), это
    НЕ "полностью здорова". ok=False с reopen_policy="manual_fail_and_refile" —
    заявка в состоянии, откуда откат в needs_package структурно невозможен
    (после approval/submit, активный ручной хендофф на CAPTCHA/MFA — state=
    'fill_blocked' с current_blocker='handoff_manual', либо легаси handoff_manual
    как отдельный state) — нужна ручная разборка через refile_application."""
    return regen.reopen_for_regen(conn, application_id)


def refile_application(conn, application_id: str) -> dict:
    """Fail+refile для нереопенабельных состояний (активный ручной хендофф —
    fill_blocked с current_blocker='handoff_manual', легаси handoff_manual и т.п.)
    — закрывает reopen_policy="manual_fail_and_refile" из
    regenerate_resume. Старая заявка помечается 'failed' (история сохраняется, не
    удаляется), новая создаётся сразу в needs_package на ту же (candidate_id,
    vacancy_id) и проходит обычный package→fill→approve→submit конвейер заново.

    ok=False с error, начинающимся на "state ... is reopenable" — заявка на самом
    деле реопенабельна, используй regenerate_resume вместо этого. ok=False с
    existing_application_id — для этой вакансии уже есть другая активная заявка,
    сначала разберись с ней."""
    return regen.refile_application(conn, application_id)


def prepare_application_answers(conn, application_id: str, *, fetcher=None) -> list[dict]:
    """Неотвеченные required вопросы формы (greenhouse) для показа в меню.

    Отфильтрованы identity/resume/cover-letter и уже отвеченные (global ⊕ per-app по
    нормализованному label). Consent оставлен агенту при показе (§3: consent не
    авто-отвечается; fill-адаптер всё равно не ставит чекбоксы)."""
    src = mcp_store.load_application_source(conn, application_id)
    if src.get("ats_family") != "greenhouse" or not src.get("source_url"):
        return []
    fetch = fetcher or greenhouse_questions.fetch_questions
    questions = fetch(src["source_url"])

    import re
    def _norm(t):
        s = re.sub(r"[^a-z0-9 ]+", " ", (t or "").lower())
        return re.sub(r"\s+", " ", s).strip()

    answered = set()
    for a in package_store.load_answers(conn, src["candidate_id"]):
        answered.add(_norm(a.field))
    for a in package_store.load_application_answers(conn, application_id):
        answered.add(_norm(a.field))

    out = []
    for q in questions:
        if not q.get("required"):
            continue
        names = set(q.get("fields", []))
        if names & _IDENTITY_FIELDS:
            continue
        if _norm(q.get("label")) in answered:
            continue
        out.append(q)
    return out


def list_telegram_leads(conn, candidate_id: str, limit: int = 20) -> list[dict]:
    """Новые для candidate_id лиды из Telegram-каналов (keyword_match первыми)
    для семантического триажа в сессии — ИИ-слой решает релевантность и
    извлекает поля, воркер только фетчит/парсит/дедуплицирует. Триаж
    пер-кандидатский: вердикт одного кандидата не скрывает лид от другого
    (см. дизайн 2026-07-17)."""
    return telegram_store.load_new_for_triage(conn, candidate_id, limit)


def triage_telegram_lead(conn, candidate_id: str, lead_id: str, is_relevant: bool,
                         role_title: str | None = None, company: str | None = None,
                         location: str | None = None, work_mode: str | None = None,
                         apply_hint: str | None = None, note: str | None = None) -> dict:
    """Записать мой (ИИ-слой) вердикт по лиду для candidate_id: релевантен ли,
    извлечённые поля, как откликаться. Лид остаётся в staging — авто-promotion
    в vacancy вне объёма (см. дизайн)."""
    extracted = {"role_title": role_title, "company": company, "location": location,
                "work_mode": work_mode, "apply_hint": apply_hint, "note": note}
    telegram_store.apply_triage_verdict(conn, lead_id, candidate_id, is_relevant, extracted)
    conn.commit()
    return {"lead_id": lead_id, "triaged": True}
