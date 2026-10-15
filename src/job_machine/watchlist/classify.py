"""Эвристика гео-открытости вакансии для LinkedIn-вотчлиста (см. дизайн
docs/superpowers/specs/2026-07-03-linkedin-company-watchlist-design.md §4).

Компания квалифицируется в вотчлист, если в тексте вакансии НЕТ явных
гео-ограничительных фраз (страна/резиденция/таймзона). Явная позитивная фраза
про "work from anywhere" и т.п. не обязательна — это только бонус-флаг
explicit_global для будущей сортировки, не условие отбора."""

import re
from dataclasses import dataclass

_RED_FLAG_PATTERNS = [
    re.compile(p) for p in [
        r"\bmust be (?:based|located|a resident|resident) in\b",
        r"\bmust reside in\b",
        r"\bus citizens? only\b",
        r"\bremote\s*\(?\s*(?:us|u\.s\.|uk|eu|canada)\s*only\s*\)?\b",
        # Известное ограничение: не требует "without sponsorship" рядом — может
        # false-positive на инклюзивных списках регионов ("authorized to work in
        # the US, UK, EU or Canada"). Калибровка на реальных LinkedIn-текстах —
        # будущая работа, не в этом срезе.
        r"\bauthoriz(?:ed|ation) to work in (?:the )?(?:us|united states|uk|eu|canada)\b",
        r"\bmust overlap\b(?=[^.]{0,40}\b(?:est|pst|cst|mst|utc|gmt|time\s*zone)\b)",
        r"\bwithin \d+\s*(?:hours?|hrs)\s*of\s*(?:est|pst|cst|mst|utc|gmt)\b",
        r"\b(?:emea|apac|americas)\s*time\s*zone required\b",
    ]
]

_POSITIVE_PATTERNS = [
    re.compile(p) for p in [
        r"\bwork from anywhere\b",
        r"\bremote[- ]first\b",
        r"\bdistributed team\b",
        r"\bglobal team\b",
        r"\bworldwide\b",
        r"\basync[- ]first\b",
    ]
]


@dataclass(frozen=True)
class ClassificationResult:
    qualifies: bool
    explicit_global: bool


def is_globally_open(description: str | None) -> ClassificationResult:
    text = (description or "").casefold()
    has_red_flag = any(p.search(text) for p in _RED_FLAG_PATTERNS)
    has_positive = any(p.search(text) for p in _POSITIVE_PATTERNS)
    return ClassificationResult(qualifies=not has_red_flag, explicit_global=has_positive)
