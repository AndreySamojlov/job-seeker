"""Чистые шаблоны Telegram-сообщений. Без БД/сети — легко тестируется.

Вход render_event — строка из store.select_pending (ключи: event_type, name,
company, title, canonical_url, payload_json). Возвращает (kind, text).
Принцип формулировок: что случилось · вакансия + кандидат · что от тебя нужно.
parse_mode='HTML' → значения экранируем html.escape.
"""
from html import escape

from job_machine.notify.models import EVENT_KIND


def _fit_line(row) -> str:
    """Скор ИНФОРМАТИВНЫЙ (не гейт, §3) — пусто, если ещё не рассчитан."""
    score = row.get("fit_score")
    if score is None:
        return ""
    band = escape(row.get("fit_band") or "")
    return f"🎯 Fit: {band} ({score}/100)\n"


def render_event(row) -> tuple[str, str]:
    et = row["event_type"]
    kind = EVENT_KIND[et]
    name = escape(row.get("name") or "?")
    company = escape(row.get("company") or "")
    role = escape(row.get("title") or "")
    head = " · ".join(p for p in (company, role) if p)   # «Adyen · Team Lead»
    payload = row.get("payload_json") or {}

    if et == "application.approval_requested":
        url = escape(row.get("canonical_url") or "")
        text = (f"📋 <b>Готово к отправке — нужен твой «ок»</b>\n"
                f"{head}\nКандидат: {name}\n"
                + _fit_line(row)
                + (f"🔗 {url}\n" if url else "")
                + "Форма заполнена до шага отправки. Одобри в кокпите — или отклони.")
    elif et == "application.submitted":
        conf = escape(payload.get("confirmation_url") or "")
        lines = ["✅ <b>Заявка отправлена</b>", head, f"Кандидат: {name}"]
        fit = _fit_line(row).rstrip("\n")
        if fit:
            lines.append(fit)
        if conf:
            lines.append(f"🔗 Подтверждение: {conf}")
        text = "\n".join(lines)
    elif et == "application.handoff_manual":
        novnc = escape(payload.get("novnc_url") or "")
        text = (f"🖐 <b>Нужен человек у браузера</b>\n{head}\nКандидат: {name}\n"
                "Причина: CAPTCHA / вход / MFA"
                + (f"\n🔗 Открыть сессию: {novnc}" if novnc else ""))
    elif et == "application.rejected":
        text = (f"❌ <b>Отказ</b>\n{head}\nКандидат: {name}\n"
                "Работодатель ответил по почте: отказ по этой заявке.")
    elif et == "application.interview_scheduled":
        text = (f"🎯 <b>Приглашение на собеседование</b>\n{head}\nКандидат: {name}\n"
                "Работодатель ответил по почте: приглашение на след. этап.")
    else:  # application.fill_blocked (только mandatory_unknown доходит сюда)
        text = (f"⛔ <b>Заявка встала на форме</b>\n{head}\nКандидат: {name}\n"
                "Не смог честно заполнить обязательное поле. "
                "Разберись в кокпите: дать ответ или пропустить.")
    return kind, text


def render_daily(stats, date_str) -> str:
    """Дневная сводка, action-first: сперва что ждёт владельца, затем оборот."""
    lines = [f"📊 <b>Сводка за {escape(date_str)}</b>"]
    for s in stats:
        lines.append(
            f"👤 {escape(s['name'])} — одобрить: {s['awaiting']} · "
            f"застряло: {s['blocked']} · подано за сутки: {s['submitted']} · "
            f"в очереди: {s['newp']}")
    return "\n".join(lines)
