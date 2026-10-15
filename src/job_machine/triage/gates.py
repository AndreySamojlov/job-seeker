"""[POLICY] Детерминированные триаж-гейты (дефект 4 аудита). Чистые функции, без I/O.

Единый источник правил отсева ДО LLM. Используют build_triage_inputs и
requeue_quick_skips. Пороги/таксономии — из GateConfig + CandidateProfile.
"""
import re
from dataclasses import dataclass, field

from job_machine.ats.urlnorm import post_identity
from job_machine.discovery.geo import classify_location
from job_machine.triage.gates_config import GateConfig


def _kw_present(keyword: str, low: str) -> bool:
    """Level-keyword-матч по границам слов, а не голый substring: короткие акронимы
    ('vp','cto') не должны ловиться ВНУТРИ слов ('cto' ⊂ 'dire[cto]r'). Границы —
    по началу/концу алфанум-последовательности; пунктуация в ключе ('sr.','jr.')
    и пробелы во фразах ('head of') сохраняются как литералы."""
    return re.search(r"(?<![a-z0-9])" + re.escape(keyword) + r"(?![a-z0-9])", low) is not None


@dataclass
class CandidateProfile:
    roles: list[str]
    locations: list[str]
    seniority_band: str | None
    company_daily_cap: int | None
    # Поля fit-2. Дефолты обязательны: gates.py конструирует профиль в тестах и
    # старых вызовах четырьмя позиционными полями.
    languages: list[str] = field(default_factory=list)
    hands_on_band: str | None = None
    domains: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)


def families_of(text: str | None, cfg: GateConfig) -> set[str]:
    """Множество role-семейств, чьи фразы встречаются в text по ГРАНИЦАМ СЛОВ (не голый
    substring — консистентно с band_of). Иначе короткое 'qa' ловилось бы внутри 'qatar',
    'sales' внутри 'wholesales' → лишние family-метки и шум fit_proxy. Границы фразы —
    по началу/концу алфанум-последовательности (пробелы/пунктуация внутри фразы —
    литералы), см. _kw_present."""
    low = (text or "").lower()
    if not low.strip():
        return set()
    return {fam for fam, phrases in cfg.role_family_map.items()
            if any(_kw_present(p, low) for p in phrases)}


def role_family_skip(title: str | None, profile: CandidateProfile,
                     cfg: GateConfig) -> str | None:
    """Skip 'role_family', если у title есть распознанное семейство и оно не
    пересекается с семействами кандидата. Unknown title/семейство → не режем."""
    title_fams = families_of(title, cfg)
    if not title_fams:
        return None
    cand_fams: set[str] = set()
    for r in profile.roles:
        cand_fams |= families_of(r, cfg)
    if title_fams & cand_fams:
        return None
    return "role_family"


def band_of(title: str | None, cfg: GateConfig) -> str | None:
    """Наивысший банд, чей keyword встречается в title. None если маркера уровня нет."""
    low = (title or "").lower()
    best_idx = None
    for band, kws in cfg.level_keywords.items():
        if any(_kw_present(k, low) for k in kws):
            idx = cfg.level_bands.index(band)
            if best_idx is None or idx > best_idx:
                best_idx = idx
    return cfg.level_bands[best_idx] if best_idx is not None else None


def level_band_skip(title: str | None, profile: CandidateProfile,
                    cfg: GateConfig) -> str | None:
    """Асимметрично: вверх строго (up_tolerance), вниз терпимо (down_tolerance).
    NULL банд кандидата или unknown-банд вакансии → не режем."""
    if not profile.seniority_band:
        return None
    if profile.seniority_band not in cfg.level_bands:
        return None
    vac = band_of(title, cfg)
    if vac is None:
        return None
    cand_i = cfg.level_bands.index(profile.seniority_band)
    vac_i = cfg.level_bands.index(vac)
    if vac_i - cand_i > cfg.level_up_tolerance:
        return "level_band"
    if cand_i - vac_i > cfg.level_down_tolerance:
        return "level_band"
    return None


def _allowed_regions(profile: CandidateProfile, cfg: GateConfig) -> set[str]:
    low_locs = [loc.lower() for loc in profile.locations]
    allowed = set()
    for region, toks in cfg.geo_region_map.items():
        if any(any(t in loc for t in toks) for loc in low_locs):
            allowed.add(region)
    return allowed


def geo_skip(location: str | None, profile: CandidateProfile,
             cfg: GateConfig) -> str | None:
    """Skip 'geo_ineligible' только для позитивно non_europe (или иного региона вне
    allowed) без глобального remote-токена. europe/unknown — никогда не режем."""
    region = classify_location(location)
    if region == "unknown":
        return None
    if region in _allowed_regions(profile, cfg):
        return None
    low = (location or "").lower()
    if any(t in low for t in cfg.geo_global_tokens):
        return None
    return "geo_ineligible"


@dataclass
class GateRow:
    vacancy_id: str
    source_url: str
    ats_family: str | None
    company: str
    title: str | None
    location: str | None
    work_mode: str | None
    has_requisition_dup_event: bool = False


@dataclass
class PassState:
    seen_posts: set[str] = field(default_factory=set)
    seen_company_titles: set[tuple[str, str]] = field(default_factory=set)
    company_counts_today: dict[str, int] = field(default_factory=dict)


def normalize_title(title: str | None) -> str:
    return re.sub(r"\s+", " ", (title or "").strip().lower())


def dedup_skip(row: GateRow, state: PassState, cfg: GateConfig) -> str | None:
    """Skip 'requisition_duplicate' по post_identity, нормализованной паре
    (company,title) или событию fill-воркера. Иначе — записать идентичность в state."""
    if row.has_requisition_dup_event:
        return "requisition_duplicate"
    pid = post_identity(row.source_url or "", row.ats_family)
    ct = ((row.company or "").strip().lower(), normalize_title(row.title))
    if pid in state.seen_posts or ct in state.seen_company_titles:
        return "requisition_duplicate"
    state.seen_posts.add(pid)
    state.seen_company_titles.add(ct)
    return None


def fit_proxy(row: GateRow, profile: CandidateProfile, cfg: GateConfig) -> int:
    """Детерминированный ранг соответствия для приоритизации при company-cap.
    role-family overlap (+2 exact / +1 raw substring) + seniority proximity
    (+2 равно / +1 ±1) + geo (+1 europe). Без LLM."""
    score = 0
    title_fams = families_of(row.title, cfg)
    cand_fams: set[str] = set()
    for r in profile.roles:
        cand_fams |= families_of(r, cfg)
    if title_fams & cand_fams:
        score += 2
    elif any(r.strip().lower() in (row.title or "").lower() for r in profile.roles if r.strip()):
        score += 1
    if profile.seniority_band and profile.seniority_band in cfg.level_bands:
        vac = band_of(row.title, cfg)
        if vac:
            d = abs(cfg.level_bands.index(vac) - cfg.level_bands.index(profile.seniority_band))
            score += 2 if d == 0 else (1 if d == 1 else 0)
    if classify_location(row.location) == "europe":
        score += 1
    return score


def apply_company_cap(survivors: list[GateRow], state: PassState,
                      profile: CandidateProfile, cfg: GateConfig):
    """Поверх выживших после гейтов 1–4: на компанию оставить топ (cap - today) по
    fit_proxy, остальные → capped. Возвращает (kept, [(row, 'company_daily_cap')])."""
    cap = profile.company_daily_cap if profile.company_daily_cap is not None \
        else cfg.company_daily_cap_default
    by_company: dict[str, list[GateRow]] = {}
    for r in survivors:
        by_company.setdefault((r.company or "").strip().lower(), []).append(r)
    kept: list[GateRow] = []
    capped: list[tuple[GateRow, str]] = []
    for company, rows in by_company.items():
        already = state.company_counts_today.get(company, 0)
        allowed = max(0, cap - already)
        ranked = sorted(rows, key=lambda r: (-fit_proxy(r, profile, cfg), r.vacancy_id))
        kept.extend(ranked[:allowed])
        capped.extend((r, "company_daily_cap") for r in ranked[allowed:])
    return kept, capped
