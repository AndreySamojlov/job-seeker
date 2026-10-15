"""DB-чтения для MCP-фасада: цели поиска, очередь, детали заявки."""
import json
from pathlib import Path

from job_machine.package.artifacts import hash_file

_PROFILE_FIELDS = ("work_mode", "locations", "roles", "salary_floor",
                   "languages", "notes")


def load_search_profile(conn, candidate_id: str) -> dict:
    """Вернуть строку search_profile как dict (jsonb-поля распакованы в списки)."""
    with conn.cursor() as cur:
        cur.execute(
            "select candidate_id, work_mode, locations, roles, salary_floor, "
            "languages, notes from search_profile where candidate_id=%s",
            (candidate_id,),
        )
        row = cur.fetchone()
    if row is None:
        return {}
    return {
        "candidate_id": row[0],
        "work_mode": row[1],
        "locations": row[2],
        "roles": row[3],
        "salary_floor": row[4],
        "languages": row[5],
        "notes": row[6],
    }


def update_search_profile(conn, patch: dict, candidate_id: str) -> None:
    """Частично обновить цели. jsonb-поля принимают списки, остальное — скаляры.

    notes — advisory-only: свободный текст для человека/агента (напр. приоритетные тиры
    локаций). Пайплайн discovery/triage/scoring его НЕ читает и НЕ парсит — реальные
    приоритеты локации/remote выражаются через geo+work_mode ось fit_score (см.
    docs/superpowers/specs/2026-07-10-funnel-quality-fixes-design.md, компонент 3)."""
    sets, params = [], []
    for field in _PROFILE_FIELDS:
        if field not in patch:
            continue
        value = patch[field]
        if field in ("work_mode", "locations", "roles", "languages"):
            sets.append(f"{field}=%s::jsonb")
            params.append(json.dumps(value))
        else:
            sets.append(f"{field}=%s")
            params.append(value)
    if not sets:
        return
    sets.append("updated_at=now()")
    params.append(candidate_id)
    # Имена колонок — только из _PROFILE_FIELDS (allowlist), значения параметризованы.
    with conn.cursor() as cur:
        cur.execute(
            f"update search_profile set {', '.join(sets)} where candidate_id=%s",
            params,
        )


def list_candidates(conn) -> list[dict]:
    """Активные кандидаты (для мульти-кандидатного выбора)."""
    with conn.cursor() as cur:
        cur.execute(
            "select candidate_id, name, headline from candidate "
            "where active order by candidate_id"
        )
        return [{"candidate_id": r[0], "name": r[1], "headline": r[2]}
                for r in cur.fetchall()]


def query_ready_queue(conn, candidate_id: str, limit: int = 20) -> list[dict]:
    """Очередь готовых к одобрению заявок кандидата, отсортированная по fit-скору
    (desc, NULL — в конце). fit_score/fit_band джойнятся из triage_result через
    application (view ready_queue не несёт vacancy_id). Скор ИНФОРМАТИВНЫЙ — не фильтр."""
    with conn.cursor() as cur:
        cur.execute(
            "select rq.application_id, rq.company, rq.role, rq.url, rq.status, "
            "rq.payload_hash, rq.screenshot_path, tr.fit_score, tr.fit_band "
            "from ready_queue rq "
            "join application a on a.application_id=rq.application_id "
            "left join triage_result tr on tr.candidate_id=rq.candidate_id "
            "and tr.vacancy_id=a.vacancy_id "
            "where rq.candidate_id=%s "
            "order by tr.fit_score desc nulls last, rq.company limit %s",
            (candidate_id, limit),
        )
        cols = [c.name for c in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    # Дублируем порядок на стороне Python (стабильно и тестируемо через FakeConn):
    # fit_score desc, NULL в конец, затем company.
    rows.sort(key=lambda r: (r.get("fit_score") is None, -(r.get("fit_score") or 0),
                             r.get("company") or ""))
    for r in rows:
        r["application_id"] = str(r["application_id"])
    return rows


def query_ready_queue_all(conn, limit: int = 50) -> list[dict]:
    """Очередь готовых к одобрению по ВСЕМ кандидатам (для read-only дашборда)."""
    with conn.cursor() as cur:
        cur.execute(
            "select application_id, candidate_id, company, role, url, status, "
            "payload_hash, screenshot_path from ready_queue order by candidate_id, company "
            "limit %s", (limit,))
        cols = [c.name for c in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    for r in rows:
        r["application_id"] = str(r["application_id"])
    return rows


def _read_verified_summary(path_str: str, content_hash: str | None):
    """Сводка отдаётся ТОЛЬКО при совпадении sha256 с artifact.content_hash (§3 —
    одобрение по чужой/перезаписанной сводке невозможно, аудит 02.07). Хеш — тем же
    hash_file, что писал content_hash при сборке пакета (единственная реализация).
    Возврат: (summary_md, summary_error, summary_source)."""
    if not content_hash:
        return "", "summary_integrity_mismatch", None
    primary = Path(path_str)
    if primary.exists() and hash_file(str(primary)) == content_hash:
        return primary.read_text(encoding="utf-8"), None, None
    fallback = primary.parent / "by-hash" / f"{content_hash}.md"
    if fallback.exists() and hash_file(str(fallback)) == content_hash:
        return fallback.read_text(encoding="utf-8"), None, "by_hash"
    return "", "summary_integrity_mismatch", None


def load_application_detail(conn, application_id: str) -> dict:
    """Детали заявки + текст disclosed summary (fail-closed по content_hash)."""
    with conn.cursor() as cur:
        cur.execute(
            "select v.company, v.title, v.canonical_url, a.state, a.payload_hash "
            "from application a join vacancy v on v.vacancy_id=a.vacancy_id "
            "where a.application_id=%s", (application_id,))
        row = cur.fetchone()
        if row is None:
            return {}
        cur.execute(
            "select path_or_uri, content_hash from artifact where application_id=%s "
            "and artifact_type='approval_summary' order by created_at desc limit 1",
            (application_id,))
        art = cur.fetchone()
    summary_md, summary_error, summary_source = "", None, None
    if art and art[0]:
        summary_md, summary_error, summary_source = _read_verified_summary(art[0], art[1])
    out = {
        "application_id": str(application_id),
        "company": row[0],
        "role": row[1],
        "url": row[2],
        "status": row[3],
        "payload_hash": row[4],
        "summary_md": summary_md,
    }
    if summary_error:
        out["summary_error"] = summary_error
    if summary_source:
        out["summary_source"] = summary_source
    return out


def load_submit_confirmation(conn, application_id: str) -> dict:
    """После submit: state + confirmation_url.

    Единственный источник confirmation_url — payload события application.submitted
    (см. finalize_confirmed в submit/store.py). Артефакт типа
    'confirmation' НЕ годится как фолбэк: его path_or_uri — это путь к PNG-файлу
    скриншота подтверждения на диске, а не URL (регресс: раньше отсутствие URL в
    событии подменялось файловым путём, выданным владельцу под видом ссылки)."""
    with conn.cursor() as cur:
        cur.execute("select state from application where application_id=%s",
                    (application_id,))
        srow = cur.fetchone()
        cur.execute(
            "select payload_json->>'confirmation_url' from event "
            "where entity_id=%s and event_type='application.submitted' "
            "order by created_at desc limit 1", (application_id,))
        erow = cur.fetchone()
        url = erow[0] if erow else None
    return {
        "status": srow[0] if srow else None,
        "confirmation_url": url,
    }


def count_by_state(conn, candidate_id: str) -> dict:
    """Агрегаты воронки кандидата: {state: count} плюс разрез по исходам работодателя.

    Исход (rejected/interview_scheduled) живёт в outcome_status, а не в state
    (миграция 0021): заявка остаётся 'submitted'. Тот же разрез уже есть в
    dashboard/store.py::count_funnel — без него здесь отказы/приглашения были
    не видны в funnel_stats (MCP) и Telegram /summary, которые питаются этой
    функцией, а не count_funnel."""
    with conn.cursor() as cur:
        cur.execute("select state, count(*) from application where candidate_id=%s "
                    "group by state", (candidate_id,))
        result = {r[0]: r[1] for r in cur.fetchall()}
        cur.execute(
            "select outcome_status, count(*) from application "
            "where candidate_id=%s and outcome_status is not null "
            "group by outcome_status", (candidate_id,))
        result["outcome"] = {r[0]: r[1] for r in cur.fetchall()}
    return result


def load_fit(conn, application_id: str) -> dict:
    """fit-разбор заявки из triage_result (через application). {} если скор не рассчитан."""
    with conn.cursor() as cur:
        cur.execute(
            "select tr.fit_score, tr.fit_band, tr.fit_breakdown, tr.material_unknowns, "
            "tr.overclaim_risks, tr.fit_summary, tr.eligibility, tr.capped_by "
            "from application a "
            "join triage_result tr on tr.candidate_id=a.candidate_id "
            "and tr.vacancy_id=a.vacancy_id where a.application_id=%s", (application_id,))
        row = cur.fetchone()
    # Проверяем ТОЛЬКО row is None: у заблокированной допуском заявки fit_score пуст,
    # и прежний ранний выход скрыл бы от владельца саму причину отказа.
    if row is None:
        return {}
    return {"fit_score": row[0], "fit_band": row[1], "fit_breakdown": row[2],
            "material_unknowns": list(row[3] or []),
            "overclaim_risks": list(row[4] or []), "fit_summary": row[5],
            "eligibility": row[6], "capped_by": list(row[7] or [])}


def load_application_source(conn, application_id) -> dict:
    """source_url + ats_family + candidate_id заявки (для фетча вопросов формы)."""
    with conn.cursor() as cur:
        cur.execute(
            "select v.source_url, v.ats_family, a.candidate_id from application a "
            "join vacancy v on v.vacancy_id=a.vacancy_id where a.application_id=%s",
            (application_id,))
        row = cur.fetchone()
    if row is None:
        return {}
    return {"source_url": row[0], "ats_family": row[1], "candidate_id": row[2]}
