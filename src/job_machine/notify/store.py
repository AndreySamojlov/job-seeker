"""DB-слой диспетчера оповещений. Выборка недоставленных кураторских событий с
маршрутными полями, ledger claim/mark, дневной дедуп и агрегаты.
"""
from job_machine.notify.models import EVENT_KIND, FILL_BLOCKED_NOTIFY


def select_pending(conn, limit: int = 50) -> list[dict]:
    """Кураторские события к отправке: новые (нет строки в ledger) + pending
    (недошедшие с прошлого тика). Join application→vacancy→candidate для текста
    и маршрута, left join triage_result для fit_score/fit_band (null, если скор
    ещё не рассчитан — информативно, не гейт). fill_blocked включается только
    при FILL_BLOCKED_NOTIFY-blocker.
    """
    with conn.cursor() as cur:
        cur.execute(
            "select e.event_id, e.event_type, c.name, v.company, v.title, "
            "       v.canonical_url, e.payload_json, tr.fit_score, tr.fit_band "
            "from event e "
            "join application a on a.application_id = e.entity_id "
            "join vacancy v on v.vacancy_id = a.vacancy_id "
            "join candidate c on c.candidate_id = a.candidate_id "
            "left join triage_result tr on tr.candidate_id = a.candidate_id "
            "                           and tr.vacancy_id = a.vacancy_id "
            "left join notification_dispatch nd on nd.event_id = e.event_id "
            "where e.event_type = any(%s) "
            "  and (e.event_type <> 'application.fill_blocked' "
            "       or e.payload_json->>'blocker' = any(%s)) "
            "  and (nd.event_id is null or nd.status = 'pending') "
            "order by e.created_at "
            "limit %s",
            (list(EVENT_KIND), list(FILL_BLOCKED_NOTIFY), limit))
        cols = [d.name for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def claim(conn, event_id, kind: str, chat_id: str) -> None:
    """Захватить событие (insert pending). unique(event_id) рубит двойную строку;
    для pending-ретрая строка уже есть → do nothing."""
    with conn.cursor() as cur:
        cur.execute(
            "insert into notification_dispatch (event_id, kind, status, chat_id) "
            "values (%s, %s, 'pending', %s) on conflict (event_id) do nothing",
            (event_id, kind, chat_id))


def mark_sent(conn, event_id, tg_message_id: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "update notification_dispatch set status='sent', tg_message_id=%s, "
            "sent_at=now() where event_id=%s", (tg_message_id, event_id))


def mark_delivered(conn, event_id, kind: str, chat_id: str) -> None:
    """Пометить событие доставленным (upsert status='sent') — для n8n-send пути,
    где отправку делает n8n (Telegram-нода), а воркер лишь фиксирует факт выдачи
    сообщения. Строки в ledger могло не быть → insert-or-update."""
    with conn.cursor() as cur:
        cur.execute(
            "insert into notification_dispatch (event_id, kind, status, chat_id, sent_at) "
            "values (%s, %s, 'sent', %s, now()) "
            "on conflict (event_id) do update set status='sent', sent_at=now()",
            (event_id, kind, chat_id))


def daily_exists(conn, summary_date) -> bool:
    with conn.cursor() as cur:
        cur.execute("select 1 from notification_daily where summary_date=%s",
                    (summary_date,))
        return cur.fetchone() is not None


def record_daily(conn, summary_date, chat_id: str, tg_message_id: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "insert into notification_daily (summary_date, chat_id, tg_message_id) "
            "values (%s, %s, %s) on conflict (summary_date) do nothing",
            (summary_date, chat_id, tg_message_id))


def daily_stats(conn) -> list[dict]:
    """Пер-кандидатные счётчики за сутки: подано (24ч), ждут одобрения,
    заблокировано (человеко-действенные current_blocker), новые (needs_package).
    """
    with conn.cursor() as cur:
        cur.execute(
            "select c.candidate_id, c.name, "
            "  (select count(*) from event e join application a2 "
            "     on a2.application_id = e.entity_id "
            "    where a2.candidate_id = c.candidate_id "
            "      and e.event_type = 'application.submitted' "
            "      and e.created_at >= now() - interval '24 hours') as submitted, "
            "  (select count(*) from application a where a.candidate_id = c.candidate_id "
            "     and a.state = 'awaiting_approval') as awaiting, "
            "  (select count(*) from application a where a.candidate_id = c.candidate_id "
            "     and a.state != 'failed' "
            "     and a.current_blocker in ('handoff_manual','mandatory_unknown',"
            "                               'captcha','mfa','anti_bot')) as blocked, "
            "  (select count(*) from application a where a.candidate_id = c.candidate_id "
            "     and a.state = 'needs_package') as newp "
            "from candidate c where c.active order by c.candidate_id")
        cols = [d.name for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]
