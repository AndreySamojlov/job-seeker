"""DB-чтения дашборда: воронка и блокеры. Очередь — reuse mcp/store."""


def count_funnel(conn) -> dict:
    """Counts по state для vacancy и application плюс разрез по исходам работодателя.

    Исход (rejected/interview_scheduled) живёт в outcome_status, а не в state
    (миграция 0021): заявка остаётся submitted. Без отдельного разреза отказы
    и приглашения не были бы видны в сводке вовсе.
    """
    with conn.cursor() as cur:
        cur.execute("select state, count(*) from vacancy group by state")
        vacancy = {r[0]: r[1] for r in cur.fetchall()}
        cur.execute("select state, count(*) from application group by state")
        application = {r[0]: r[1] for r in cur.fetchall()}
        cur.execute("select outcome_status, count(*) from application "
                    "where outcome_status is not null group by outcome_status")
        outcome = {r[0]: r[1] for r in cur.fetchall()}
    return {"vacancy": vacancy, "application": application, "outcome": outcome}


def count_blockers(conn) -> list[dict]:
    """Заявки с current_blocker, сгруппированные по типу: count + возраст старейшей.

    state != 'failed' — рефайленная заявка (regen.refile_application) намеренно
    оставляет current_blocker старой записи нетронутым (диагностическая история),
    иначе она бы вечно засоряла дашборд как "живой" блокер."""
    with conn.cursor() as cur:
        cur.execute(
            "select current_blocker, count(*), min(updated_at) "
            "from application where current_blocker is not null and state != 'failed' "
            "group by current_blocker order by count(*) desc"
        )
        return [
            {"blocker": r[0], "count": r[1],
             "oldest": r[2].isoformat() if r[2] else None}
            for r in cur.fetchall()
        ]
