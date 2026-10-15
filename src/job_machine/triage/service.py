from dataclasses import dataclass, field

from job_machine import provenance
from job_machine.triage import store
from job_machine.triage.gates import (
    GateRow, PassState, _kw_present, apply_company_cap, dedup_skip, geo_skip,
    level_band_skip, role_family_skip)
from job_machine.triage.gates_config import load_gate_config
from job_machine.triage.htmltext import strip_html
from job_machine.triage.models import TriageInput


@dataclass
class PullSummary:
    inputs: list = field(default_factory=list)
    quick_skipped: int = 0
    skipped_no_content: int = 0
    transient: int = 0
    claims_version: str | None = None


def _role_matches(title: str | None, roles: list[str]) -> bool:
    """True если title содержит хотя бы одну роль из профиля кандидата по ГРАНИЦАМ СЛОВ
    (не substring — иначе 'Team Lead' ловит 'Engineering Team Leader', 'QA' ловит 'Qatar').
    None-title → True (LLM решает, чтобы не пропустить неизвестное)."""
    if title is None:
        return True
    low = title.lower()
    return any(_kw_present(r.strip().lower(), low) for r in roles if r.strip())


def _quick_skip(work_mode: str | None, title: str | None, roles: list[str]) -> str | None:
    """Вернуть причину пропуска ('title_mismatch') или None — в LLM.
    work_mode-префильтр снят (релокацию учитываем, C-022). Роль-фильтр — из
    search_profile.roles конкретного кандидата (Task 8: замена захардкоженного
    _TARGET_RE на реальный пер-кандидатный фильтр)."""
    if not _role_matches(title, roles):
        return "title_mismatch"
    return None


def _fetch_and_build(conn, client, row: GateRow, candidate_id: str, claims,
                     summary: PullSummary) -> None:
    """ATS-aware fetch → strip → TriageInput для одной выжившей строки. Обновляет
    summary (inputs / skipped_no_content / transient) на месте."""
    from job_machine.discovery.sources import client_for as ats_client_for

    ats_family = row.ats_family
    # Для GH (или NULL) используем переданный client (FakeClient в тестах).
    # Для Ashby/Lever создаём ATS-специфичный клиент (парсит свой JSON формат).
    if ats_family and ats_family != "greenhouse":
        try:
            fetch_client = ats_client_for(ats_family)()
            owns_client = True
        except (ValueError, Exception):
            fetch_client = client
            owns_client = False
    else:
        fetch_client = client
        owns_client = False
    try:
        content = fetch_client.fetch_content(row.source_url)
    except Exception:  # noqa: BLE001
        # Транзиентная ошибка (сеть/5xx/429 после исчерпанных ретраев) — НЕ
        # подтверждённое 404. Не помечаем stale: вакансия остаётся 'verified'
        # и попадёт в следующий /triage/pull, а не хоронится навсегда.
        if owns_client:
            getattr(fetch_client, "close", lambda: None)()
        summary.transient += 1
        return
    if owns_client:
        getattr(fetch_client, "close", lambda: None)()
    if not content:
        store.mark_stale_no_content(conn, row.vacancy_id)
        conn.commit()
        summary.skipped_no_content += 1
        return
    summary.inputs.append(TriageInput(
        vacancy_id=str(row.vacancy_id), candidate_id=candidate_id, title=row.title,
        company=row.company, location=row.location, work_mode=row.work_mode,
        job_text=strip_html(content), claims=claims,
    ))


def build_triage_inputs(conn, client, candidate_id: str, limit: int = 25) -> PullSummary:
    """Детерминированно собрать triage-input для одного кандидата двухфазно:
    pull verified без triage_result → детерминированные гейты (дефект 4 аудита) →
    ATS-aware fetch выживших → strip → claims (из Postgres).

    Фаза 1 (построчно): role_family → level_band → geo → dedup → title_mismatch
    (слабый unknown-фолбэк _quick_skip: ловит роли, которые ни один семейный гейт не
    распознал); первый непустой → record_quick_skip(reason) + commit. Фаза 2 (батч):
    apply_company_cap над выжившими → capped → record_quick_skip. Выжившие после обеих
    фаз → fetch/strip.
    client — запасной (Greenhouse); для Ashby/Lever диспатчим свой клиент."""
    profile = store.load_candidate_profile(conn, candidate_id)
    claims = store.load_claims(conn, candidate_id)
    cfg = load_gate_config()
    seen_posts, seen_cts = store.load_seen_requisitions(conn, candidate_id)
    state = PassState(seen_posts=seen_posts, seen_company_titles=seen_cts,
                      company_counts_today=store.load_company_counts_today(conn, candidate_id))
    summary = PullSummary(claims_version=provenance.claims_version(claims))

    survivors: list[GateRow] = []
    for (vid, source_url, title, company, location, work_mode, ats_family,
         has_dup_event) in store.pull_untriaged_for_candidate(conn, candidate_id, limit):
        row = GateRow(vacancy_id=vid, source_url=source_url or "", ats_family=ats_family,
                      company=company or "", title=title, location=location,
                      work_mode=work_mode, has_requisition_dup_event=bool(has_dup_event))
        reason = (role_family_skip(title, profile, cfg)
                  or level_band_skip(title, profile, cfg)
                  or geo_skip(location, profile, cfg)
                  or dedup_skip(row, state, cfg)
                  or _quick_skip(work_mode, title, profile.roles))
        if reason:
            store.record_quick_skip(conn, candidate_id, vid, reason,
                                    {"title": title, "company": company,
                                     "location": location, "work_mode": work_mode})
            conn.commit()
            summary.quick_skipped += 1
            continue
        survivors.append(row)

    # Фаза 2: company_daily_cap поверх выживших (топ-N по fit_proxy).
    kept, capped = apply_company_cap(survivors, state, profile, cfg)
    for row, reason in capped:
        store.record_quick_skip(conn, candidate_id, row.vacancy_id, reason,
                                {"title": row.title, "company": row.company})
        conn.commit()
        summary.quick_skipped += 1

    for row in kept:
        _fetch_and_build(conn, client, row, candidate_id, claims, summary)
    return summary


def build_triage_inputs_all(conn, client, candidate_ids, limit: int = 25) -> PullSummary:
    """Собрать triage-input по НЕСКОЛЬКИМ кандидатам за один pull: цикл по
    candidate_ids, конкатенация inputs (каждый уже тегирован candidate_id) и
    счётчиков. Для n8n-флоу /triage/pull_all — планировщик триажит всех активных
    кандидатов их собственными ролями и claims."""
    combined = PullSummary()
    for cid in candidate_ids:
        s = build_triage_inputs(conn, client, cid, limit)
        combined.inputs.extend(s.inputs)
        combined.quick_skipped += s.quick_skipped
        combined.skipped_no_content += s.skipped_no_content
        combined.transient += s.transient
    return combined


def apply_triage(conn, verdict, candidate_id: str, claims_version: str | None = None) -> str:
    """Применить один structured verdict для candidate_id; коммит per-item (без
    батч-отката)."""
    route = store.apply_verdict(conn, verdict, candidate_id, claims_version)
    conn.commit()
    return route
