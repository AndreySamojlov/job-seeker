"""Детерминированный гео-скорер вакансий.

Никогда не делает hard-skip: даже onsite вне Европы получает ненулевой приоритет
(relocation_candidate). Используется как сортировочный сигнал, не как фильтр.
"""

from dataclasses import dataclass, field


# Ключевые слова европейских локаций (casefold)
EUROPE_HINTS: frozenset[str] = frozenset({
    "amsterdam", "berlin", "london", "paris", "madrid", "barcelona",
    "rome", "milan", "vienna", "zurich", "stockholm", "oslo", "copenhagen",
    "helsinki", "brussels", "prague", "warsaw", "budapest", "bucharest",
    "lisbon", "porto", "dublin", "luxembourg", "bern", "geneva",
    "netherlands", "germany", "france", "spain", "italy", "austria",
    "switzerland", "sweden", "norway", "denmark", "finland", "belgium",
    "czech", "poland", "hungary", "romania", "portugal", "ireland",
    "luxembourg", "cyprus", "malta", "estonia", "latvia", "lithuania",
    "slovakia", "slovenia", "croatia", "bulgaria", "greece",
    "eu", "europe", "european", "emea",
    "remote - eu", "remote - europe", "remote eu", "remote europe",
})

# Ключевые слова НЕ-европейских регионов (casefold)
NON_EUROPE_HINTS: frozenset[str] = frozenset({
    "united states", "us only", "usa only", "u.s.", "u.s.a",
    "new york", "san francisco", "seattle", "austin", "chicago", "boston",
    "los angeles", "denver", "atlanta", "miami", "dallas",
    "canada", "toronto", "vancouver", "montreal",
    "india", "bangalore", "hyderabad", "mumbai", "pune",
    "china", "beijing", "shanghai",
    "singapore", "australia", "sydney", "melbourne",
    "brazil", "são paulo", "sao paulo",
    "japan", "tokyo",
    "south africa", "cape town", "johannesburg", "pretoria", "durban",
    "united arab emirates", "uae", "dubai", "abu dhabi",
    "israel", "tel aviv", "saudi arabia", "riyadh",
    "latin america", "latam", "apac",
})


@dataclass(frozen=True)
class GeoVerdict:
    region: str        # "europe" | "non_europe" | "unknown"
    work_mode: str     # "remote" | "hybrid" | "onsite" | "unknown"
    priority: int      # 0–100, выше = интереснее
    flags: list[str] = field(default_factory=list)


def classify_location(location: str | None) -> str:
    """Вернуть 'europe', 'non_europe' или 'unknown'."""
    loc = (location or "").casefold()
    if not loc.strip():
        return "unknown"

    # Сначала проверяем европейские хинты (точные подстроки)
    for hint in EUROPE_HINTS:
        if hint in loc:
            return "europe"

    # Затем не-европейские
    for hint in NON_EUROPE_HINTS:
        if hint in loc:
            return "non_europe"

    return "unknown"


# Матрица приоритетов (work_mode, region) → priority
_MATRIX: dict[tuple[str, str], int] = {
    ("remote", "europe"):     100,
    ("remote", "unknown"):     80,
    ("hybrid", "europe"):      70,
    ("onsite", "europe"):      50,
    ("remote", "non_europe"):  40,
    ("hybrid", "unknown"):     30,
    ("hybrid", "non_europe"):  20,
    ("onsite", "non_europe"):  20,
    ("onsite", "unknown"):     30,
    ("unknown", "europe"):     40,
    ("unknown", "unknown"):    30,
    ("unknown", "non_europe"): 15,
}


def score_vacancy(work_mode: str, location: str | None) -> GeoVerdict:
    """Рассчитать гео-приоритет вакансии.

    Никогда не возвращает priority=0 — любая вакансия остаётся кандидатом.
    """
    region = classify_location(location)
    mode = (work_mode or "unknown").casefold()
    if mode not in ("remote", "hybrid", "onsite"):
        mode = "unknown"

    priority = _MATRIX.get((mode, region), 15)
    flags: list[str] = []
    if region == "non_europe" and mode == "onsite":
        flags.append("relocation_candidate")
    if mode == "remote" and region == "europe":
        flags.append("eu_remote")

    return GeoVerdict(region=region, work_mode=mode, priority=priority, flags=flags)
