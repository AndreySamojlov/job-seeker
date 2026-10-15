"""Структурная классификация блокеров браузерной сессии (ТЗ §12.3).

Чистая функция над сигналами страницы — без Playwright, тестируется юнитом.
Сигналы собирает inspect.extract_signals(page); здесь только маппинг в метку.
Метки совпадают со словарём application.current_blocker (спека §3).
"""

BLOCKERS = (
    "captcha",
    "login_wall",
    "mfa",
    "account_required",
    "anti_bot",
    "mandatory_unknown",  # эмитится доменным слоем (план 5), не отсюда
    "vacancy_removed",
    "ambiguous",
    "broken_flow",
)


# Человеко-решаемые блокеры (строгое подмножество BLOCKERS): владелец проходит их
# вручную через noVNC handoff в ТОЙ ЖЕ browser-сессии (captcha/mfa/login/account-wall/
# anti-bot интерстишл), поэтому сессию нельзя освобождать до повторной попытки. Единый
# источник для guards/browser.py (сборка _NEXT_ACTION) и
# fill/service.py::resume_after_handoff (still_blocked vs terminal) — не дублировать
# локальными списками (review 07.07: неполный tuple пропускал login_wall).
# mandatory_unknown/vacancy_removed/ambiguous/broken_flow сюда не входят: это
# терминальные состояния, которые не решаются повторной попыткой в той же сессии.
HUMAN_RETRYABLE_BLOCKERS = (
    "captcha",
    "mfa",
    "account_required",
    "login_wall",
    "anti_bot",
)


def classify_page(signals):
    """Вернуть метку блокера из BLOCKERS или None, если страница чистая.

    signals — dict с признаками страницы: has_captcha, has_anti_bot_interstitial,
    has_mfa_prompt, has_account_creation, has_login_form, http_status, form_count,
    real_field_count (fallback для SPA без тега <form>, напр. Ashby), final_url
    (для детекта Greenhouse soft-404 редиректа на {company}?error=true).
    Порядок проверок — от самого жёсткого блокера к мягкому.
    """
    if signals.get("has_captcha"):
        return "captcha"
    if signals.get("has_anti_bot_interstitial"):
        return "anti_bot"
    if signals.get("has_mfa_prompt"):
        return "mfa"
    if signals.get("has_account_creation"):
        return "account_required"
    if signals.get("has_login_form"):
        return "login_wall"
    final_url = signals.get("final_url") or ""
    if "error=true" in final_url:
        # Greenhouse молча редиректит снятые/закрытые вакансии на
        # {company}?error=true с HTTP 200 — verify (только код ответа) это не ловит.
        # Более сильный сигнал, чем локальный подсчёт полей ниже: даже если на странице
        # листинга есть посторонние поля (поиск по вакансиям), это точно не наша форма.
        return "vacancy_removed"
    status = signals.get("http_status")
    if status is not None and status >= 400:
        return "broken_flow"
    if signals.get("form_count", 0) == 0 and signals.get("real_field_count", 0) < 3:
        return "ambiguous"
    return None
