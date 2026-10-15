"""Оркестрация заполнения: pull → gate → inspect → map → fill → record. Per-item commit.

Контур безопасности: гарды раскрытия и resume-hash до любого взаимодействия с формой;
fail-closed на любой блокер inspect; стоп до submit. Несопоставленные required-поля
(mandatory_unknown) больше НЕ терминальный стоп на этой стадии — страница остаётся
живой (browser.retain) и передаётся агенту (state=agent_fill_pending, спека
2026-08-06); сам гард mandatory_unknown остаётся страховкой на submit-пути.
"""

import logging
import os
import hashlib
from pathlib import Path

import httpx

from job_machine.ats.urlnorm import same_post
from job_machine.browser.blockers import HUMAN_RETRYABLE_BLOCKERS
from job_machine.discovery.store import mark_stale
from job_machine.fill import gate, store
from job_machine.fill.adapter import map_fields
from job_machine.fill.models import FillRunSummary
from job_machine.package.artifacts import hash_file, write_rebound_artifacts
from job_machine.package.builder import rebind_destination
from job_machine.package.summary import render_summary
from job_machine.package.models import PackageManifest
from job_machine.package import hashing
from job_machine.consent import looks_like_consent

log = logging.getLogger(__name__)

# Сколько минут агенту отводится на одну заявку. Дольше — страница возвращается
# воркеру: висящая сессия это утёкший браузерный контекст (инцидент 2026-07-06).
AGENT_FILL_TIMEOUT_MINUTES = int(os.environ.get("AGENT_FILL_TIMEOUT_MINUTES", "15"))


def agent_fill_context(conn, application_id: str, session_id: str) -> dict:
    """Read disclosed values on the worker that owns /data; never query new facts."""
    row = store.load_agent_package(conn, application_id)
    if not row or row['session_id'] != session_id:
        return {'ok': False, 'error': 'stale_session'}
    try:
        data = Path(row['path']).read_bytes()
        if hashlib.sha256(data).hexdigest() != row['content_hash']:
            raise ValueError('hash mismatch')
        manifest = PackageManifest.model_validate_json(data)
        payload = hashing.payload_hash(manifest.destination_url, manifest.resume.content_hash,
                                       manifest.answers, manifest.consents)
        if (manifest.application_id != str(application_id) or
                payload != row['payload_hash'] or payload != manifest.payload_hash):
            raise ValueError('binding mismatch')
    except (OSError, ValueError, TypeError):
        return {'ok': False, 'error': 'package_unverified'}
    return {'ok': True, 'payload_hash': payload,
            'answers': [a.model_dump() for a in manifest.answers if not looks_like_consent(a.field)]}


def sweep_agent_fill_timeouts(conn, browser, timeout_minutes: int) -> int:
    """Вернуть страницы заявок, которые агент не добил вовремя. Возвращает их число.

    Критерий выборки — наличие agent_fill_session_id, а НЕ state (см.
    store.pull_stale_agent_fills): refile_application уводит заявку из
    agent_fill_pending в failed мимо агента, не трогая сессию, и retained-страница
    осталась бы жить вечно — обычный dispose её не закрывает, sweep_orphaned_contexts
    не видит (она числится в реестре сессий).

    Блокер ставится только заявкам, всё ещё ждущим агента: если состояние уже
    сменилось (refile увёл заявку в failed), страницу всё равно надо освободить,
    но переписывать её исход задним числом нельзя.
    """
    reclaimed = 0
    for row in store.pull_stale_agent_fills(conn, timeout_minutes):
        if not store.lock_stale_agent_fill(conn, row, timeout_minutes):
            conn.rollback()
            continue
        sid = row["session_id"]
        try:
            browser.release(sid)
        except httpx.HTTPError as exc:
            if not (isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 404):
                log.warning("release протухшей агент-сессии %s: %s", sid, exc)
                conn.rollback()
                continue
        if row["state"] in {"agent_fill_pending", "pre_submit_ready", "approved"}:
            store.record_fill_blocked(conn, row["application_id"], "agent_fill_timeout",
                                      {"timeout_minutes": timeout_minutes})
        store.clear_agent_fill_session(conn, row["application_id"])
        conn.commit()
        reclaimed += 1
    return reclaimed


def run_fill(conn, browser, limit: int = 10,
             candidate_id: str | None = None) -> FillRunSummary:
    """candidate_id — скоуп fill-очереди этим кандидатом (иначе глобальный свип)."""
    sweep_agent_fill_timeouts(conn, browser, AGENT_FILL_TIMEOUT_MINUTES)
    summary = FillRunSummary()
    for row in store.pull_fillable(conn, limit, candidate_id):
        summary.pulled += 1
        aid = row["application_id"]
        try:
            _fill_one(conn, browser, row, summary)
        except Exception as exc:  # noqa: BLE001 — изоляция падения по заявке
            conn.rollback()
            store.record_fill_blocked(conn, aid, "broken_flow", {"error": str(exc)})
            conn.commit()
            summary.errors += 1
            summary.blocked += 1
    return summary


def _fill_one(conn, browser, row, summary) -> None:
    aid = row["application_id"]
    sid = browser.create_session()
    try:
        blocker = _process_fill(conn, browser, aid, row, sid,
                                lambda manifest: browser.inspect(sid, manifest.destination_url))
        if blocker is None:
            summary.pre_submit_ready += 1
        elif blocker == "agent_fill_pending":
            summary.agent_fill_pending += 1
        else:
            summary.blocked += 1
    finally:
        # Для retained-сессии (агент-путь) обычный dispose — no-op: страница
        # переживает выход из _fill_one и ждёт агента.
        browser.dispose(sid)


def resume_after_handoff(conn, browser, application_id: str, session_id: str) -> dict:
    """Продолжить fill в СУЩЕСТВУЮЩЕЙ browser-сессии после того, как владелец вручную
    прошёл CAPTCHA/MFA через handoff_browser (§3 ТЗ). Использует inspect_current —
    БЕЗ повторной навигации, которая сбросила бы cookies/anti-bot токены, полученные
    при прохождении.

    Возвращает {"ok": True, "status": "pre_submit_ready"} при успехе;
    {"ok": True, "status": "agent_fill_pending"} — код не сопоставил часть required-полей,
        страница передаётся агенту, сессия НЕ освобождается (retain уже сделан внутри
        _process_fill);
    {"ok": False, "error": "not_found"} — заявки нет;
    {"ok": False, "error": "session_expired"} — сессия потеряна (воркер перезапущен);
    {"ok": False, "error": "still_blocked", "blocker": ...} — блокер из
        HUMAN_RETRYABLE_BLOCKERS (captcha/mfa/account_required/login_wall/anti_bot) ещё
        активен, сессия НЕ освобождается (попытку можно повторить);
    {"ok": False, "error": <blocker>} — новый терминальный блокер после снятия
        капчи (destination_redirect/broken_flow/guard-имя), сессия освобождается.

    Не-404 httpx.HTTPStatusError (5xx воркера и т.п.) пробрасывается наружу
    БЕЗ release: владение сессией в этом случае возвращается вызывающему —
    угадывать судьбу сессии на основании непонятной ошибки воркера опаснее,
    чем оставить её как есть для ручного разбора.

    {"ok": False, "error": "broken_flow"} — непредвиденная ошибка внутри _process_fill
        (например, удалённый с диска файл резюме, битый manifest.json, ошибка БД) —
        та же изоляция, что в run_fill: rollback, record_fill_blocked('broken_flow'),
        сессия освобождается (в отличие от still_blocked, повторять здесь нечего).
    """
    row = store.load_fillable_row_by_id(conn, application_id)
    if row is None:
        return {"ok": False, "error": "not_found"}

    try:
        blocker = _process_fill(conn, browser, application_id, row, session_id,
                                lambda manifest: browser.inspect_current(session_id))
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return {"ok": False, "error": "session_expired"}
        raise
    except Exception as exc:  # noqa: BLE001 — та же изоляция, что в run_fill (broken_flow per-item)
        conn.rollback()
        store.record_fill_blocked(conn, application_id, "broken_flow", {"error": str(exc)})
        conn.commit()
        browser.release(session_id)
        return {"ok": False, "error": "broken_flow"}

    if blocker is None:
        browser.release(session_id)
        return {"ok": True, "status": "pre_submit_ready"}
    if blocker == "agent_fill_pending":
        # Страница передана агенту — освобождать её нельзя.
        return {"ok": True, "status": "agent_fill_pending"}
    if blocker == "stale_fill":
        return {"ok": False, "error": "stale_fill"}
    if blocker in HUMAN_RETRYABLE_BLOCKERS:
        return {"ok": False, "error": "still_blocked", "blocker": blocker}
    browser.release(session_id)
    return {"ok": False, "error": blocker}


def _process_fill(conn, browser, application_id, row, sid, make_inspect) -> str | None:
    """Общее ядро: resume-safety → гарды раскрытия → inspect → destination-контроль →
    map → fill → record. Не создаёт и не закрывает сессию — это забота вызывающего.

    make_inspect(manifest) -> InspectResult — свежая навигация (_fill_one) или чтение
    текущей страницы (resume_after_handoff); получает manifest, т.к. свежей навигации
    нужен manifest.destination_url.

    Возвращает None при успехе (state → pre_submit_ready) или строку блокера,
    под которой заявка была остановлена (уже записан в БД внутри этой функции)."""
    if not store.lock_fillable(conn, application_id):
        conn.rollback()
        return "stale_fill"
    resume = row["resume"] or {}

    # 0. Явный resume-блок: заявка без привязанного резюме не маскируется в KeyError/
    #    broken_flow (review MAJOR-2) — это диагностируемая остановка resume-safety.
    if not resume.get("path"):
        store.record_fill_blocked(conn, application_id, "broken_flow",
                                  {"reason": "no resume bound to package"})
        conn.commit()
        return "broken_flow"

    manifest = store.load_manifest(row["manifest_path"])

    # 1. Resume safety: пересчитываем hash файла СЕЙЧАС, сверяем с раскрытым в пакете.
    actual_hash = hash_file(resume["path"])  # FileNotFoundError → broken_flow (внешний except)
    g = gate.check_fill_gate(
        summary_artifacts=row["summary_artifacts"],
        resume_artifact={"content_hash": actual_hash},
        disclosed_resume_hash=resume.get("content_hash"),
    )
    if g is not None:
        store.record_guard_block(conn, application_id, g)
        conn.commit()
        return g.guard_name

    result = make_inspect(manifest)
    blocker = gate.inspect_block_label(result.blocker)
    if blocker is not None:
        store.record_fill_blocked(conn, application_id, blocker,
                                  {"url": manifest.destination_url})
        if blocker == "vacancy_removed":
            mark_stale(conn, row["vacancy_id"])
        conn.commit()
        return blocker

    # Destination-контроль (аудит 02.07): фактический URL после редиректов.
    final_url = result.form_schema.url
    if not same_post(final_url, manifest.destination_url, row.get("ats_family")):
        store.record_destination_redirect(conn, application_id, row["vacancy_id"],
                                          source_url=manifest.destination_url,
                                          final_url=final_url)
        conn.commit()
        return "destination_redirect"

    mapping = map_fields(manifest.answers, manifest.consents, result.form_schema,
                         row.get("ats_family"))
    # Детерминированный проход идёт ПЕРВЫМ и всегда: он заполняет всё, что честно
    # сопоставил, и прикладывает резюме. Агент подключается к странице, где уже
    # стоят имя, почта, телефон и файл — ему остаётся только то, чего код не понял.
    # Порядок принципиален: пока проверка unmatched_required стояла до fill, агенту
    # доставалась пустая форма и вся детерминированная работа выбрасывалась
    # (обнаружено на живом прогоне OKX 2026-08-07).
    fill_result = browser.fill(sid, mapping.fields, resume_path=resume["path"],
                                consent_checks=mapping.auto_consents)
    if not fill_result.stopped_before_submit:  # инвариант устава §3 (defense-in-depth)
        store.record_fill_blocked(conn, application_id, "broken_flow",
                                  {"reason": "fill did not stop before submit"})
        conn.commit()
        return "broken_flow"

    if mapping.unmatched_required:
        # Не терминальный стоп: страница остаётся живой и уходит агенту (спека
        # 2026-08-06). Гард mandatory_unknown при этом никуда не делся — он
        # по-прежнему стоит перед необратимым кликом на стороне submit-воркера.
        try:
            recorded = store.record_agent_fill_pending(
                conn, application_id, session_id=sid, page_url=final_url,
                unmatched=mapping.unmatched_required,
                filled_fields=fill_result.filled,
                resume_attached=fill_result.resume_attached)
            if not recorded:
                conn.rollback()
                return "stale_fill"
            browser.retain(sid)
            conn.commit()
        except Exception:
            # Сессия уже retained, но записи о ней в БД не будет — обычный dispose
            # её не закроет, а свип таймаутов не найдёт (искать нечего). Такая
            # страница осталась бы жить до перезапуска воркера: именно так копятся
            # браузерные контексты, положившие хост 2026-07-06.
            conn.rollback()
            browser.release(sid)
            raise
        return "agent_fill_pending"

    if final_url != manifest.destination_url:
        # Тот же пост, но URL отличается (хост/регион): ребинд пакета на
        # фактический destination — approval увидит и одобрит реальный URL.
        source_url = manifest.destination_url
        manifest2 = rebind_destination(manifest, final_url)
        descs = write_rebound_artifacts(row["manifest_path"], manifest2,
                                        render_summary(manifest2))
        store.record_destination_resolved(
            conn, application_id, source_url=source_url, final_url=final_url,
            manifest=manifest2, artifact_descs=descs)
    else:
        store.record_final_apply_url(conn, application_id, final_url)

    store.record_pre_submit_ready(
        conn, application_id, filled_fields=fill_result.filled,
        resume_attached=fill_result.resume_attached,
        screenshot_path=fill_result.screenshot_path)
    conn.commit()
    return None
