"""Submit orchestration. Per-claim commit; exception isolation per claimed attempt.

Конвейер: claim (лиз) → проверки → mark_clicking (необратимая граница, потребление
approval) → клик → финализация по доказательству. Зеркалит fill/service.py.

[SAFETY] Инвариант: если клик уже начат (mark_clicking вернул True), заявка НЕ
может вернуться в очередь и НЕ может стать submit_blocked. Любая ошибка после этой
точки даёт submit_unknown, а не блокировку и не повтор.
"""
from datetime import datetime, timezone

from job_machine.ats.urlnorm import confirmation_mismatch, same_post
from job_machine.browser.schema import SubmitResult
from job_machine.fill.adapter import map_fields
from job_machine.fill.store import load_manifest
from job_machine.package.artifacts import hash_file
from job_machine.submit import gate, store
from job_machine.submit.models import SubmitRunSummary


def _load_manifest(path: str):
    """Thin alias — allows monkeypatching in tests."""
    return load_manifest(path)


def _recover_stale(conn) -> None:
    """[SAFETY] Расклинить зависшее ДО того, как брать новую работу.

    `recover_stale_attempts` не имела ни одного вызывающего: `/submit/recover`
    существовал, но его никто не дёргал ни по расписанию, ни из кода, поэтому
    заявка, чей воркер умер, висела в `submitting` вечно. Штатный прогон подачи —
    единственная точка, которая гарантированно исполняется по расписанию, и
    единственная, где порядок «сперва расклинить, потом клеймить» вообще имеет
    смысл: отдельный cron такого порядка не даёт. Расклинивание идёт своей
    транзакцией — оно не должно откатываться вместе с ошибкой чьей-то подачи.
    """
    store.recover_stale_attempts(conn)
    conn.commit()


def run_submit(conn, browser, limit: int = 10, *,
               worker_id: str = "job-submit") -> SubmitRunSummary:
    summary = SubmitRunSummary()
    _recover_stale(conn)
    for _ in range(limit):
        row = store.claim_next(conn, worker_id)
        if row is None:
            break
        conn.commit()
        summary.pulled += 1
        _run_claim(conn, browser, row, summary)
    return summary


def run_submit_one(conn, browser, application_id: str, *,
                   worker_id: str = "job-submit") -> SubmitRunSummary:
    """Подача ровно одной одобренной заявки по id (per-id путь кокпита)."""
    summary = SubmitRunSummary()
    _recover_stale(conn)
    row = store.claim_application(conn, application_id, worker_id)
    if row is None:
        return summary  # нечего клеймить: не approved, уже занята или рубильник выключен
    conn.commit()
    summary.pulled += 1
    _run_claim(conn, browser, row, summary)
    return summary


def _run_claim(conn, browser, row, summary) -> None:
    """Изоляция падения: заклеймленная заявка не может остаться висеть в submitting."""
    try:
        _submit_claim(conn, browser, row, summary)
    except Exception as exc:  # noqa: BLE001
        conn.rollback()
        if store.can_continue_verification(conn, row["attempt_id"]):
            # Клик уже начат — исход неизвестен, возврат в очередь запрещён.
            store.finalize_unknown(conn, row["attempt_id"],
                                   SubmitResult(click_performed=True), "broken_flow")
        else:
            _fail_claim(conn, row, "broken_flow", {"error_type": type(exc).__name__})
        conn.commit()
        summary.errors += 1
        summary.blocked += 1


def _fail_claim(conn, row, blocker: str, detail: dict) -> None:
    """Закрыть попытку до клика; промах закрытия не оставлять молчаливым.

    `fail_claimed_attempt` пишет только по `status='claimed'`. Если к этому моменту
    лиз протух и `recover_stale_attempts` уже закрыл попытку (или её увёл другой
    воркер), она возвращает False. Раньше возврат игнорировался и вызывающий всё
    равно коммитил: заявка оставалась в `submitting` с попыткой в `clicking`, и в
    аудите не было ничего. Теперь такой промах попадает в event-лог.
    """
    if not store.fail_claimed_attempt(conn, row["attempt_id"], blocker, detail):
        store.record_orphaned_attempt(conn, row["application_id"], row["attempt_id"],
                                      blocker, detail)


def _block_claim(conn, row, summary, blocker: str, detail: dict) -> None:
    _fail_claim(conn, row, blocker, detail)
    conn.commit()
    summary.blocked += 1


def _submit_claim(conn, browser, row, summary) -> None:
    aid = row["application_id"]
    now = datetime.now(tz=timezone.utc)

    stop = gate.check_submit_gate(conn, aid, now)
    if stop is not None:
        _block_claim(conn, row, summary, stop.guard_name, {"guard": stop.guard_name})
        return

    resume = row.get("resume") or {}
    if not resume.get("path"):
        _block_claim(conn, row, summary, "broken_flow",
                     {"reason": "no resume bound to package"})
        return

    manifest = _load_manifest(row["manifest_path"])
    if manifest.payload_hash != row["payload_hash"]:
        _block_claim(conn, row, summary, "manifest_integrity_mismatch",
                     {"manifest_payload_hash": manifest.payload_hash,
                      "db_payload_hash": row["payload_hash"]})
        return

    sid = browser.create_session()
    try:
        result = browser.inspect(sid, manifest.destination_url)
        if result.blocker is not None:
            _block_claim(conn, row, summary, result.blocker,
                         {"url": manifest.destination_url})
            return

        final_url = result.form_schema.url
        if not same_post(final_url, manifest.destination_url, row.get("ats_family")):
            _block_claim(conn, row, summary, "destination_redirect",
                         {"expected_url": manifest.destination_url,
                          "final_url": final_url})
            return

        mapping = map_fields(manifest.answers, manifest.consents,
                             result.form_schema, row.get("ats_family"))
        if mapping.unmatched_required:
            _block_claim(conn, row, summary, "mandatory_unknown",
                         {"unmatched": mapping.unmatched_required})
            return

        actual_hash = hash_file(resume["path"])
        g = gate.check_resume_hash_gate(
            resume_artifact={"content_hash": actual_hash},
            disclosed_resume_hash=resume.get("content_hash"))
        if g is not None:
            _block_claim(conn, row, summary, g.guard_name, {"guard": g.guard_name})
            return

        # Необратимая граница. После этой строки откат невозможен.
        if not store.mark_clicking(conn, row["attempt_id"]):
            _block_claim(conn, row, summary, "broken_flow",
                         {"reason": "attempt drifted before click"})
            return
        conn.commit()

        submit_result = browser.submit(sid, mapping.fields,
                                       resume_path=resume.get("path"),
                                       consent_checks=mapping.auto_consents)

        if store.finalize_confirmed(conn, row["attempt_id"], submit_result):
            conn.commit()
            if confirmation_mismatch(submit_result.confirmation_url,
                                     manifest.destination_url, row.get("ats_family")):
                store.record_destination_mismatch(
                    conn, aid, expected_url=manifest.destination_url,
                    confirmation_url=submit_result.confirmation_url)
                conn.commit()
            summary.submitted += 1
            return

        store.finalize_unknown(
            conn, row["attempt_id"], submit_result,
            submit_result.failure_signal or "no_confirmation")
        conn.commit()
        summary.blocked += 1
    finally:
        browser.dispose(sid)
