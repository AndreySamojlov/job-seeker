"""Канонический детектор consent/декларация-полей (§3). Единый источник истины для
inspect (browser) и fill-адаптера — чтобы списки хинтов не разъезжались.

Принцип §3: ошибаться в сторону НЕ-проставления. Список намеренно широкий —
лучше не заполнить легитимный чекбокс-опцию (уйдёт в unmatched → человек), чем
автоматически проставить согласие."""

import re

CONSENT_HINTS = (
    "consent", "agree", "privacy", "gdpr", "terms", "accept", "acknowledge",
    "authoriz", "authoris", "declaration", "declare", "i understand",
    "policy", "disclaimer", "permission", "opt in", "opt-in", "i certify",
)


def looks_like_consent(label) -> bool:
    low = (label or "").lower()
    return any(h in low for h in CONSENT_HINTS)


# Стоячее согласие по тексту вопроса — расширение _STANDING_CONSENT_NAMES (name-based,
# fill/adapter.py) для company-custom вопросов со случайным question_id, которые name-based
# путь поймать не может. Точный allowlist (НЕ fuzzy) — намеренно узкий: шире, чем
# CONSENT_HINTS выше, значило бы риск авто-проставить незнакомое согласие (§3, владелец
# 2026-07-15; confidentiality/NDA-категория — владелец 2026-07-24). Список расширяется
# вручную по мере появления новых кейсов в бэклоге.
_STANDING_LABEL_SUBSTRINGS = (
    "point of data transfer",
    "privacy disclosure",
    "personal information policy",
    "candidate privacy policy",
    "applicant privacy policy",
    "ai responsible use policy",
    "confidential information",
)
# Заякорено на конец строки (\W*$ — только хвостовые пунктуация/пробелы): privacy-фраза
# должна быть последней мыслью в вопросе, независимо от префикса ("review ...", "Zscaler
# ...", просто голое "<Компания> Privacy Policy"). Без якоря "review ... privacy notice and
# consent to marketing emails" тоже матчил бы — бандл с исключённой §3 категорией
# (marketing) прошёл бы как стоячее privacy-согласие (code-review finding, 2026-07-15).
_STANDING_LABEL_PATTERN = re.compile(r"privacy (policy|notice)\W*$")

# Токены НЕ-авторизованных категорий (marketing/talent-pool, ToS, background/credit check,
# передача третьим лицам) — их СОВПАДЕНИЕ вместе с privacy/confidentiality-фразой блокирует
# матч целиком, даже если якорь/substring выше сработал. Закрывает и "privacy-последней"
# зеркало 2026-07-15 инцидента (\W*$-якорь ловит только "privacy-первой" бандлы), и
# небезопасно широкий unanchored-substring "confidential information" (review, 2026-07-24):
# без денилиста он матчил бы согласие на background check / credit check / раскрытие
# третьим лицам просто потому, что где-то в предложении встретилась эта фраза.
_DISALLOWED_COOCCURRING_TOKENS = (
    "marketing", "newsletter", "talent pool", "talent-pool",
    "terms of service", "terms and conditions",
    "background check", "credit check",
    "third party", "third-party",
)


def looks_like_standing_label_consent(label) -> bool:
    low = (label or "").lower()
    if any(tok in low for tok in _DISALLOWED_COOCCURRING_TOKENS):
        return False
    return any(s in low for s in _STANDING_LABEL_SUBSTRINGS) or bool(
        _STANDING_LABEL_PATTERN.search(low)
    )


# Prefer-not-to-say/decline-опции demographic/EEO-групп (gender/race/veteran/disability) —
# реальные тексты, сверено с живым Greenhouse DOM (Adyen gender/race, Twilio veteran/
# disability, 2026-07-07; переприменено 2026-07-24 после утери на устаревшей ветке).
DECLINE_HINTS = (
    "prefer not to say",
    "prefer not to answer",
    "decline to answer",
    "decline to self identify",
    "decline to self-identify",
    "don't wish to answer",
    "do not wish to answer",
)


def looks_like_decline_option(label) -> bool:
    low = (label or "").lower()
    return any(h in low for h in DECLINE_HINTS)
