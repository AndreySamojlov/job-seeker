from job_machine import audit


def upsert_vacancy(conn, rec) -> str | None:
    """Вставить вакансию; на конфликте canonical_url — no-op. Возвращает vacancy_id
    при реальной вставке (тогда же эмитит vacancy.discovered), иначе None."""
    with conn.cursor() as cur:
        cur.execute(
            "insert into vacancy (source, source_url, canonical_url, company, "
            "normalized_company, title, normalized_title, location, work_mode, "
            "ats_family, discovered_at, vacancy_status, state) "
            "values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s, now(), 'discovered', 'discovered') "
            "on conflict (canonical_url) do nothing returning vacancy_id",
            (rec.source, rec.source_url, rec.canonical_url, rec.company,
             rec.normalized_company, rec.title, rec.normalized_title, rec.location,
             rec.work_mode, rec.ats_family),
        )
        row = cur.fetchone()
    if row is None:
        return None
    vacancy_id = row[0]
    audit.emit_event(conn, "vacancy", vacancy_id, "vacancy.discovered",
                     {"canonical_url": rec.canonical_url, "source": rec.source})
    return str(vacancy_id)


def load_profile_role_patterns(conn) -> list[str]:
    """ILIKE-паттерны целевых ролей — объединение roles ВСЕХ активных кандидатов
    (verify — общий пул вакансий без кандидатского скоупа, см. slice 1 design).
    Нет активных кандидатов/ролей → [] (чистый FIFO)."""
    with conn.cursor() as cur:
        cur.execute(
            "select sp.roles from search_profile sp "
            "join candidate c on c.candidate_id = sp.candidate_id "
            "where c.active"
        )
        rows = cur.fetchall()
    patterns: set[str] = set()
    for (roles,) in rows:
        for r in (roles or []):
            if isinstance(r, str) and r.strip():
                patterns.add(f"%{r.strip().lower()}%")
    return sorted(patterns)


def pull_discovered(conn, limit: int, priority_patterns: list[str] | None = None):
    """(vacancy_id, source_url, ats_family) для вакансий в статусе discovered.
    ats_family нужен вызывающему коду (run_verify) для диспатча ATS-специфичного
    клиента — единый client не умеет проверять чужой API/URL-формат (Ashby/Lever).
    С priority_patterns целевые тайтлы идут первыми (новейшие вперёд),
    остальные — прежний FIFO (старейшие первыми)."""
    if not priority_patterns:
        with conn.cursor() as cur:
            cur.execute(
                "select vacancy_id, source_url, ats_family from vacancy "
                "where vacancy_status = 'discovered' "
                "order by discovered_at nulls first limit %s",
                (limit,),
            )
            return cur.fetchall()
    with conn.cursor() as cur:
        cur.execute(
            "select vacancy_id, source_url, ats_family from ("
            "  select vacancy_id, source_url, ats_family, discovered_at, "
            "         (normalized_title ilike any(%s)) as is_target "
            "  from vacancy where vacancy_status = 'discovered'"
            ") sub "
            "order by is_target desc, "
            "case when is_target then discovered_at end desc, "
            "discovered_at nulls first limit %s",
            (priority_patterns, limit),
        )
        return cur.fetchall()


def mark_verified(conn, vacancy_id) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "update vacancy set vacancy_status='verified', state='verified', "
            "verified_at=now() where vacancy_id = %s",
            (vacancy_id,),
        )
    audit.emit_event(conn, "vacancy", vacancy_id, "vacancy.verified", {})


def mark_stale(conn, vacancy_id) -> None:
    # stale — dead/error-ветка (миграция 0002): пишем только vacancy_status,
    # lifecycle-state НЕ трогаем.
    with conn.cursor() as cur:
        cur.execute(
            "update vacancy set vacancy_status='stale', verified_at=now() "
            "where vacancy_id = %s",
            (vacancy_id,),
        )
    audit.emit_event(conn, "vacancy", vacancy_id, "vacancy.stale", {})
