import uuid

from psycopg.types.json import Json

from job_machine import audit
from job_machine.triage.models import ClaimRecord


def record_quick_skip(conn, candidate_id: str, vacancy_id, reason: str,
                      detail: dict | None = None) -> None:
    """Детерминированный пре-фильтр: записать skip без LLM-вызова, в
    пер-кандидатный леджер triage_result. Общий vacancy.state НЕ трогаем —
    вакансия остаётся общим пулом для других кандидатов.
    reason: 'work_mode' | 'title_mismatch' | 'role_family' | 'level_band' |
    'geo_ineligible' | 'requisition_duplicate' | 'company_daily_cap' (детерминированные
    гейты, дефект 4 аудита). reason — свободный payload события (verdict всегда 'skip').
    detail — произвольный payload для аудита. Коммит — на стороне вызывающего."""
    vid = vacancy_id if isinstance(vacancy_id, uuid.UUID) else uuid.UUID(str(vacancy_id))
    with conn.cursor() as cur:
        cur.execute(
            "insert into triage_result (candidate_id, vacancy_id, verdict) "
            "values (%s,%s,'skip') on conflict (candidate_id, vacancy_id) do nothing",
            (candidate_id, vid))
    audit.emit_event(conn, "vacancy", vid, "vacancy.quick_skipped",
                     {"reason": reason, "candidate_id": candidate_id, **(detail or {})})


def mark_stale_no_content(conn, vacancy_id) -> None:
    """Подтверждённый 404 (вакансия точно снята) — перевести в 'stale', зеркалит
    discovery.store.mark_stale (тоже ставит verified_at=now()). Без перевода из
    'verified' вакансия навсегда занимает начало очереди на каждый следующий
    /triage/pull (order by verified_at nulls first), блокируя LLM-триаж свежих
    вакансий. Транзиентные ошибки (сеть/5xx) сюда не попадают — см. build_triage_inputs.
    Коммит — на стороне вызывающего."""
    vid = vacancy_id if isinstance(vacancy_id, uuid.UUID) else uuid.UUID(str(vacancy_id))
    with conn.cursor() as cur:
        cur.execute("update vacancy set vacancy_status='stale', verified_at=now() "
                    "where vacancy_id=%s", (vid,))
    audit.emit_event(conn, "vacancy", vid, "vacancy.stale", {"reason": "no_content"})


def upsert_claims(conn, claims: list[ClaimRecord], candidate_id: str) -> None:
    with conn.cursor() as cur:
        for c in claims:
            cur.execute(
                "insert into claim (candidate_id, claim_id, claim_text, status, proof, "
                "safe_use, updated_at) values (%s,%s,%s,%s,%s,%s, now()) "
                "on conflict (candidate_id, claim_id) do update set "
                "claim_text=excluded.claim_text, status=excluded.status, "
                "proof=excluded.proof, safe_use=excluded.safe_use, updated_at=now()",
                (candidate_id, c.claim_id, c.claim_text, c.status, c.proof, c.safe_use),
            )


def load_claims(conn, candidate_id: str) -> list[ClaimRecord]:
    with conn.cursor() as cur:
        cur.execute("select claim_id, claim_text, status, proof, safe_use "
                    "from claim where candidate_id=%s order by claim_id", (candidate_id,))
        rows = cur.fetchall()
    return [ClaimRecord(claim_id=r[0], claim_text=r[1], status=r[2],
                        proof=r[3], safe_use=r[4]) for r in rows]


def pull_verified_untriaged(conn, limit: int):
    """(vacancy_id, source_url, title, company, location, work_mode, ats_family) для verified."""
    with conn.cursor() as cur:
        cur.execute(
            "select vacancy_id, source_url, title, company, location, work_mode, ats_family "
            "from vacancy where vacancy_status='verified' "
            "order by verified_at nulls first limit %s",
            (limit,),
        )
        return cur.fetchall()


def load_candidate_roles(conn, candidate_id: str) -> list[str]:
    with conn.cursor() as cur:
        cur.execute("select roles from search_profile where candidate_id=%s", (candidate_id,))
        row = cur.fetchone()
    return list(row[0]) if row and row[0] else []


def load_candidate_profile(conn, candidate_id: str):
    """CandidateProfile из search_profile + cloud_skill (стек кандидата).
    Отсутствующий кандидат → безопасный пустой профиль (гейты вырождаются в no-skip).
    Пустые поля fit-2 дают 0 по своим векторам — это правило «неизвестно = 0»,
    поэтому профиль каждого активного кандидата обязан быть заполнен (§6 спеки)."""
    from job_machine.triage.gates import CandidateProfile
    with conn.cursor() as cur:
        cur.execute("select roles, locations, seniority_band, company_daily_cap, "
                    "languages, hands_on_band, domains "
                    "from search_profile where candidate_id=%s", (candidate_id,))
        row = cur.fetchone()
        cur.execute("select name from cloud_skill where candidate_id=%s",
                    (candidate_id,))
        skills = [r[0] for r in cur.fetchall()]
    if not row:
        return CandidateProfile(roles=[], locations=[], seniority_band=None,
                                company_daily_cap=None, skills=skills)
    return CandidateProfile(
        roles=list(row[0] or []), locations=list(row[1] or []),
        seniority_band=row[2], company_daily_cap=row[3],
        languages=list(row[4] or []), hands_on_band=row[5],
        domains=list(row[6] or []), skills=skills)


def _load_vacancy_axes(conn, vid):
    """(title, location, work_mode) вакансии для осей role/seniority/geo.
    Отсутствует → (None, None, None)."""
    with conn.cursor() as cur:
        cur.execute("select title, location, work_mode from vacancy where vacancy_id=%s",
                    (vid,))
        row = cur.fetchone()
    return (row[0], row[1], row[2]) if row else (None, None, None)


def application_id_for(conn, candidate_id, vid):
    """application_id заявки кандидата по вакансии (или None). Для событий пересчёта."""
    with conn.cursor() as cur:
        cur.execute("select application_id from application "
                    "where candidate_id=%s and vacancy_id=%s", (candidate_id, vid))
        row = cur.fetchone()
    return row[0] if row else None


def score_for_verdict(conn, v, candidate_id: str):
    """I/O-обёртка над обеими фазами fit-2: собрать профиль + оси вакансии + конфиги.
    Возвращает (eligibility_result, fit | None). При блокировке допуска скор
    пригодности НЕ считается — fit остаётся None."""
    from job_machine.triage.eligibility import check_eligibility
    from job_machine.triage.gates_config import load_gate_config
    from job_machine.triage.score_config import load_score_config
    from job_machine.triage.scoring import compute_fit_score
    vid = uuid.UUID(str(v.vacancy_id))
    profile = load_candidate_profile(conn, candidate_id)
    gate_cfg, score_cfg = load_gate_config(), load_score_config()
    elig = check_eligibility(v, profile, gate_cfg)
    if elig.blocked:
        return elig, None
    title, location, work_mode = _load_vacancy_axes(conn, vid)
    fit = compute_fit_score(v, title, location, profile, gate_cfg, score_cfg,
                            work_mode=work_mode)
    return elig, fit


def load_company_counts_today(conn, candidate_id: str) -> dict[str, int]:
    """Число заявок кандидата за сегодня по company (btrim+lower). Питает
    company_daily_cap: cap считается поверх уже созданных сегодня заявок. Ключ
    btrim(lower(...)) совпадает с '.strip().lower()' в apply_company_cap — иначе
    company с краевыми пробелами не сматчились бы и дневной счётчик не применился."""
    with conn.cursor() as cur:
        cur.execute(
            "select lower(btrim(v.company)), count(*) from application a "
            "join vacancy v on v.vacancy_id=a.vacancy_id "
            "where a.candidate_id=%s and a.created_at::date = now()::date "
            "group by lower(btrim(v.company))", (candidate_id,))
        return {r[0]: r[1] for r in cur.fetchall() if r[0]}


def load_seen_requisitions(conn, candidate_id: str):
    """(seen_posts, seen_company_titles) из уже затриаженных этим кандидатом вакансий.
    Инициализирует PassState для dedup-гейта, чтобы дубли одного requisition,
    затриаженные в прошлых pull'ах, распознавались и в текущем."""
    from job_machine.ats.urlnorm import post_identity
    from job_machine.triage.gates import normalize_title
    with conn.cursor() as cur:
        cur.execute(
            "select v.source_url, v.ats_family, v.company, v.title from vacancy v "
            "join triage_result tr on tr.vacancy_id=v.vacancy_id "
            "where tr.candidate_id=%s", (candidate_id,))
        rows = cur.fetchall()
    posts = {post_identity(r[0] or "", r[1]) for r in rows}
    cts = {((r[2] or "").strip().lower(), normalize_title(r[3])) for r in rows}
    return posts, cts


def pull_untriaged_for_candidate(conn, candidate_id: str, limit: int):
    """(vacancy_id, source_url, title, company, location, work_mode, ats_family,
    has_requisition_dup_event) для verified-вакансий, ещё не имеющих строки в
    triage_result для этого кандидата. Последнее поле — флаг наличия события
    vacancy.requisition_duplicate (от fill-воркера), питает dedup-гейт.
    Общий пул vacancy НЕ фильтруется по 'triaged'/'skipped' vacancy_status —
    диспозиция теперь пер-кандидатная, в леджере."""
    with conn.cursor() as cur:
        cur.execute(
            "select v.vacancy_id, v.source_url, v.title, v.company, v.location, "
            "v.work_mode, v.ats_family, "
            "exists (select 1 from event e where e.entity_id=v.vacancy_id "
            "and e.event_type='vacancy.requisition_duplicate') "
            "from vacancy v "
            "where v.vacancy_status='verified' and not exists "
            "(select 1 from triage_result t where t.vacancy_id=v.vacancy_id "
            "and t.candidate_id=%s) order by v.verified_at nulls first limit %s",
            (candidate_id, limit))
        return cur.fetchall()


def _fit_facts(v) -> dict:
    """Факты извлечения v2 (ВХОД модели) для персиста рядом с вердиктом. Отличать от
    колонки eligibility, которая несёт ВЫХОД фазы допуска. Без этого снимка
    recompute_fit не может восстановить векторы hands_on/domain/stack и обнуляет их —
    штатный пересчёт после смены весов ронял бэнд у всей очереди (ревью 2026-08-15)."""
    return {"eligibility": v.eligibility.model_dump(),
            "domain": v.domain.model_dump(),
            "stack": v.stack.model_dump(),
            "hands_on": v.hands_on.model_dump()}


def _verdict_payload(v, route: str, fit=None, skip_reason: str | None = None,
                     downgraded: bool = False) -> dict:
    p = {
        "verdict": v.verdict, "route": route, "fit_summary": v.fit_summary,
        "hard_requirements": [r.model_dump() for r in v.hard_requirements],
        "material_unknowns": v.material_unknowns,
        "overclaim_risks": v.overclaim_risks,
    }
    if fit is not None:
        p["fit_score"] = fit.score
        p["fit_band"] = fit.band
        p["capped_by"] = list(fit.capped_by)
    if skip_reason is not None:
        p["skip_reason"] = skip_reason
    if downgraded:
        p["verdict_downgraded"] = True
        p["original_verdict"] = "skip"
    return p


# 5 категорических исключений §3 CLAUDE.md, синхронно с TriageVerdict.skip_category
# (models.py). Единый источник правды на оба места — эта константа + Literal там.
_CATEGORICAL_SKIP = {"mandatory_language", "license_or_qualification",
                     "clearance_or_citizenship", "onsite_location", "domain_mismatch"}


def apply_verdict(conn, v, candidate_id: str, claims_version: str | None = None) -> str:
    """Детерминированный маршрут по structured verdict. Возвращает route:
    'skipped' | 'needs_package'.
    Пер-кандидатно: пишет строку в леджер triage_result(candidate_id, vacancy_id) и,
    при needs_package, application.candidate_id. Общий vacancy.state/vacancy_status
    НЕ трогается — диспозиция ушла в леджер, вакансия остаётся общим пулом для других
    кандидатов (Task 8).

    Модель fit-2 — две фазы, вызываются по порядку через score_for_verdict:
    1. Допуск (eligibility.check_eligibility). Блокировка по позитивному факту (§3:
       mandatory_language / clearance_or_citizenship / onsite_location) → verdict='skip'
       с этой категорией, и скор пригодности НЕ считается вовсе (fit_score/fit_band
       остаются NULL) — оценивать «насколько хорош» кандидат для вакансии, куда его не
       пустят, бессмысленно, а записанное число вводило бы в заблуждение в очереди и
       отчётах. Неизвестности допуска (elig.unknowns) НЕ блокируют — дописываются в
       material_unknowns и раскрываются владельцу вместе с фактическим вердиктом.
    2. Пригодность (scoring.compute_fit_score), только если допуск не заблокировал.
       Узкое исключение — fit-floor (band=D, funnel-quality-fixes 2026-07-10, спека
       2026-08-15-fit-vectors §4.3 подтверждает: сохраняется в прежнем виде): это не про
       честные оговорки при реально приемлемом фите, а про заведомо плохое соответствие —
       такие вакансии не доходят до disclosed-summary вообще, гасятся детерминированно до
       пакета. Не конфликтует с духом политики §3 (там речь про gap у иначе годного
       кандидата), но формально это новый детерминированный блок — см.
       skip_reason='fit_floor' в audit-event.
       ВАЖНО про band D в fit-2: правило «неизвестно = 0» держит вектор в знаменателе
       даже когда фактов нет, поэтому band D значит не только «плохое соответствие», но
       и «фактов извлекли мало». Поэтому fit_floor ОБУСЛОВЛЕН РАЗБОРОМ (авторизация
       владельца 2026-08-15): при флаге requirements_not_parsed гейт не применяется, и
       такая вакансия идёт дальше с раскрытием, а не гасится молча.

    Политика disclosed-caveats (§3, авторизация владельца 2026-06-29): apply/
    apply_with_caveat → needs_package; material_unknowns/overclaim_risks НЕ блокируют,
    а раскрываются в disclosed-summary (package.summary) и одобряются пер-вакансийно.
    claims_version — провенанс снимка career-evidence-vault (B7), рядом с артефактом."""
    # vacancy_id приходит строкой (JSON-граница n8n); БД-столбцы — uuid. psycopg3 шлёт
    # str как text → 'uuid = text' упадёт. Конвертируем на границе в uuid.UUID.
    vid = uuid.UUID(str(v.vacancy_id))
    elig, fit = score_for_verdict(conn, v, candidate_id)
    skip_reason = None

    # Фаза 1 — допуск. Блокировка по позитивному факту → skip с категорией §3;
    # скор пригодности не считается вовсе (fit_score остаётся NULL).
    if elig.blocked:
        v.verdict = "skip"
        v.skip_category = elig.category
        skip_reason = "eligibility_block"
    else:
        # Фаза 2 — пригодность. fit-floor: заведомо плохое соответствие гасится до
        # disclosed-summary (funnel-quality-fixes 2026-07-10). ОБУСЛОВЛЕН РАЗБОРОМ
        # (авторизация владельца 2026-08-15): гейт применяется, только если требования
        # реально извлечены. Иначе он гасил бы не «плохие» вакансии, а «непонятые» —
        # без разбора требований композит не может превысить 24.5 балла, то есть band D
        # гарантирован при любых идеальных роли и гео.
        if (v.verdict != "skip" and fit.band == "D"
                and "requirements_not_parsed" not in fit.flags):
            v.verdict = "skip"
            skip_reason = "fit_floor"

    # Неизвестности фазы допуска раскрываются владельцу, а не блокируют (§3).
    if elig.unknowns:
        v.material_unknowns = [*(v.material_unknowns or []), *elig.unknowns]

    # Симметричный бэкстоп (funnel-quality-fixes 2026-07-15): skip на band A/B без
    # категорического обоснования — даунгрейд в apply_with_caveat. Не применяется,
    # когда сработала блокировка допуска: там категория как раз доказана.
    downgraded = False
    if (fit is not None and v.verdict == "skip" and skip_reason != "fit_floor"
            and fit.band in ("A", "B") and v.skip_category not in _CATEGORICAL_SKIP):
        v.material_unknowns = [
            *(v.material_unknowns or []),
            f"Triage initially flagged for skip (band {fit.band}) without a categorical "
            f"reason under CLAUDE.md §3; downgraded to disclosed caveat. Original "
            f"reasoning: {v.fit_summary}",
        ]
        v.verdict = "apply_with_caveat"
        downgraded = True

    if v.verdict == "skip":
        with conn.cursor() as cur:
            cur.execute(
                "insert into triage_result (candidate_id, vacancy_id, verdict, fit_summary, "
                "material_unknowns, overclaim_risks, claims_version, hard_requirements, "
                "fit_score, fit_band, fit_breakdown, fit_score_version, eligibility, "
                "capped_by, fit_facts) "
                "values (%s,%s,'skip',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "on conflict (candidate_id, vacancy_id) do update set verdict='skip', "
                "hard_requirements=excluded.hard_requirements, fit_score=excluded.fit_score, "
                "fit_band=excluded.fit_band, fit_breakdown=excluded.fit_breakdown, "
                "fit_score_version=excluded.fit_score_version, "
                "eligibility=excluded.eligibility, capped_by=excluded.capped_by, "
                "fit_facts=excluded.fit_facts",
                (candidate_id, vid, v.fit_summary, Json(v.material_unknowns or []),
                 Json(v.overclaim_risks or []), claims_version,
                 Json([r.model_dump() for r in v.hard_requirements]),
                 (fit.score if fit else None), (fit.band if fit else None),
                 (Json(fit.breakdown()) if fit else None),
                 (fit.version if fit else None),
                 Json(elig.payload()),
                 (list(fit.capped_by) if fit is not None else None),
                 Json(_fit_facts(v))))
            # Флип apply→skip: припарковать ранее созданную заявку, если она ещё в
            # needs_package без блокера — иначе под skip-роль соберётся пакет.
            # current_blocker!=NULL исключает её из pull_needs_package/ready_queue.
            # Заявки, уже ушедшие дальше needs_package, не трогаем.
            cur.execute(
                "update application set current_blocker='triage_skip', updated_at=now() "
                "where candidate_id=%s and vacancy_id=%s and state='needs_package' "
                "and current_blocker is null",
                (candidate_id, vid))
        audit.emit_event(conn, "vacancy", vid, "vacancy.skipped",
                         {**_verdict_payload(v, "skipped", fit, skip_reason),
                          "candidate_id": candidate_id, "claims_version": claims_version})
        return "skipped"

    # Политика «disclosed caveats» (явная авторизация владельца 2026-06-29, CLAUDE.md §3):
    # apply / apply_with_caveat ПРОХОДЯТ к needs_package (если не срезаны fit-floor'ом
    # выше — band=D гасится ДО этой точки, до всякого disclosed-summary). material_unknowns и
    # overclaim_risks больше НЕ блокируют детерминированно — они едут в event-payload
    # (_verdict_payload) и ОБЯЗАТЕЛЬНО раскрываются в disclosed-summary (package.summary)
    # как честные оговорки. Контроль честности перенесён с блока на пару
    # «раскрытие в сводке + пер-вакансийное явное одобрение владельцем». Никакого
    # вымысла: резюме/ответы по-прежнему уважают safe_use claim-ов (gaps не заявляются).
    with conn.cursor() as cur:
        cur.execute(
            "insert into triage_result (candidate_id, vacancy_id, verdict, fit_summary, "
            "material_unknowns, overclaim_risks, claims_version, hard_requirements, "
            "fit_score, fit_band, fit_breakdown, fit_score_version, eligibility, "
            "capped_by, fit_facts) "
            "values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "on conflict (candidate_id, vacancy_id) do update set verdict=excluded.verdict, "
            "hard_requirements=excluded.hard_requirements, fit_score=excluded.fit_score, "
            "fit_band=excluded.fit_band, fit_breakdown=excluded.fit_breakdown, "
            "fit_score_version=excluded.fit_score_version, "
            "eligibility=excluded.eligibility, capped_by=excluded.capped_by, "
            "fit_facts=excluded.fit_facts",
            (candidate_id, vid, v.verdict, v.fit_summary, Json(v.material_unknowns or []),
             Json(v.overclaim_risks or []), claims_version,
             Json([r.model_dump() for r in v.hard_requirements]),
             (fit.score if fit else None), (fit.band if fit else None),
             (Json(fit.breakdown()) if fit else None),
             (fit.version if fit else None),
             Json(elig.payload()),
             (list(fit.capped_by) if fit is not None else None),
             Json(_fit_facts(v))))
        # Guarded insert: реплей того же (candidate_id, vacancy_id) НЕ создаёт вторую
        # заявку (леджер триажа идемпотентен, но INSERT application сам по себе — нет).
        # Событие application.triaged эмитим только при реальной вставке.
        cur.execute(
            "insert into application (vacancy_id, candidate_id, verdict, package_status, "
            "current_blocker, state, claims_version) "
            "select %s,%s,%s,'none',NULL,'needs_package',%s "
            "where not exists (select 1 from application "
            "where candidate_id=%s and vacancy_id=%s) "
            "returning application_id",
            (vid, candidate_id, v.verdict, claims_version, candidate_id, vid),
        )
        row = cur.fetchone()
    if row:
        application_id = row[0]
        audit.emit_event(conn, "application", application_id, "application.triaged",
                         {**_verdict_payload(v, "needs_package", fit, downgraded=downgraded),
                          "candidate_id": candidate_id, "claims_version": claims_version})
    return "needs_package"
