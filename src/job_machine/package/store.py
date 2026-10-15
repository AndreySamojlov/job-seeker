import uuid

from job_machine import audit
from job_machine.package.models import AnswerRecord, PackageManifest


def upsert_answers(conn, answers: list[AnswerRecord], candidate_id: str) -> None:
    with conn.cursor() as cur:
        for a in answers:
            cur.execute(
                "insert into answer (candidate_id, field, value, state, rule, updated_at) "
                "values (%s,%s,%s,%s,%s, now()) "
                "on conflict (candidate_id, field) do update set "
                "value=excluded.value, state=excluded.state, rule=excluded.rule, "
                "updated_at=now()",
                (candidate_id, a.field, a.value, a.state, a.rule),
            )


def load_answers(conn, candidate_id: str) -> list[AnswerRecord]:
    with conn.cursor() as cur:
        cur.execute("select field, value, state, rule from answer "
                    "where candidate_id=%s order by field", (candidate_id,))
        rows = cur.fetchall()
    return [AnswerRecord(field=r[0], value=r[1], state=r[2], rule=r[3] or "")
            for r in rows]


def pull_needs_package(conn, limit: int = 10,
                       candidate_id: str | None = None) -> list[dict]:
    """Заявки к сборке пакета: needs_package И без блокера (current_blocker IS NULL —
    defense-in-depth; политика disclosed-caveats §3 триаж missing_fact больше не ставит,
    но фильтр держим). Джойн vacancy + последний application.triaged event.

    candidate_id — если задан, очередь скоупится этим кандидатом; иначе глобальная
    FIFO по всем кандидатам (обратная совместимость с auto-свипом). Без скоупа старший
    бэклог одного кандидата затеняет очередь другого (баг мульти-кандидат-сессии)."""
    scope = ""
    params: list = []
    if candidate_id is not None:
        scope = "and a.candidate_id = %s "
        params.append(candidate_id)
    params.append(limit)
    with conn.cursor() as cur:
        cur.execute(
            "select a.application_id, a.vacancy_id, a.candidate_id, v.company, v.title, "
            "v.canonical_url, v.ats_family, "
            "(select e.payload_json from event e where e.entity_id = a.application_id "
            " and e.event_type='application.triaged' order by e.created_at desc limit 1) "
            "from application a join vacancy v on v.vacancy_id = a.vacancy_id "
            "where a.state='needs_package' and a.current_blocker is null "
            "and a.resume_artifact_id is not null "
            f"{scope}"
            "order by a.created_at limit %s",
            tuple(params),
        )
        rows = cur.fetchall()
    out = []
    for aid, vid, candidate_id, company, title, url, ats, triaged in rows:
        triaged = triaged or {}
        out.append({
            "application_id": str(aid), "vacancy_id": str(vid),
            "candidate_id": candidate_id,
            "company": company or "", "role": title or "",
            "destination_url": url or "", "ats_family": ats,
            "fit_summary": triaged.get("fit_summary", ""),
            "hard_requirements": triaged.get("hard_requirements", []),
            "material_unknowns": triaged.get("material_unknowns", []),
            "overclaim_risks": triaged.get("overclaim_risks", []),
        })
    return out


def record_package(conn, m: PackageManifest, artifact_descs: list[dict],
                   answers_version: str | None = None) -> None:
    """Записать прочие артефакты, проставить хеши + package_ready, эмитнуть событие.
    Resume-артефакт УЖЕ создан resume-воркером (application.resume_artifact_id) — не дублируем.
    answers_version — провенанс снимка application-answer-vault (B7), рядом с payload_hash, НЕ внутри."""
    aid = uuid.UUID(m.application_id)
    with conn.cursor() as cur:
        for d in artifact_descs:
            cur.execute(
                "insert into artifact (application_id, artifact_type, path_or_uri, "
                "content_hash) values (%s,%s,%s,%s)",
                (aid, d["artifact_type"], d["path"], d["content_hash"]))
        cur.execute(
            "update application set package_status='package_ready', state='package_ready', "
            "answers_hash=%s, consents_hash=%s, payload_hash=%s, answers_version=%s, "
            "updated_at=now() where application_id=%s",
            (m.answers_hash, m.consents_hash, m.payload_hash, answers_version, aid))
    audit.emit_event(conn, "application", aid, "application.package_ready", {
        "payload_hash": m.payload_hash, "answers_hash": m.answers_hash,
        "consents_hash": m.consents_hash, "answers_version": answers_version,
        "resume": {"filename": m.resume.filename, "content_hash": m.resume.content_hash},
        "warnings": [w.field for w in m.warnings],
        "artifacts": {d["artifact_type"]: d["path"] for d in artifact_descs}})


def load_application_answers(conn, application_id) -> list[AnswerRecord]:
    """Per-application ответы формы (locked) для слияния с глобальными."""
    with conn.cursor() as cur:
        cur.execute(
            "select field, value, state, rule from application_answer "
            "where application_id=%s order by field",
            (uuid.UUID(str(application_id)),))
        rows = cur.fetchall()
    return [AnswerRecord(field=r[0], value=r[1], state=r[2], rule=r[3] or "")
            for r in rows]


def upsert_application_answers(conn, application_id, answers: list[AnswerRecord]) -> None:
    """Upsert per-application ответов по (application_id, field)."""
    aid = uuid.UUID(str(application_id))
    with conn.cursor() as cur:
        for a in answers:
            cur.execute(
                "insert into application_answer "
                "(application_id, field, value, state, rule, updated_at) "
                "values (%s,%s,%s,%s,%s, now()) "
                "on conflict (application_id, field) do update set "
                "value=excluded.value, state=excluded.state, rule=excluded.rule, "
                "updated_at=now()",
                (aid, a.field, a.value, a.state, a.rule))
