"""[POLICY] Детерминированная оценка соответствия (fit-2). Чистые функции, без I/O.

Вторая фаза модели: семь векторов, взвешенный композит, мягкие пороги-потолки.
Первая фаза (допуск) — triage/eligibility.py.

Два инварианта:
1. НЕИЗВЕСТНО = 0, вектор остаётся в знаменателе. В fit-1 отсутствующая ось
   выбрасывалась, и вакансия оценивалась только по «удачным» осям — так 577 строк,
   которых модель никогда не видела, получили band A со средним скором 89.
2. Мягкий порог только ОПУСКАЕТ бэнд (потолок C) и никогда не поднимает. Заявка
   продолжает жить и раскрываться в сводке — жёсткий блок остаётся привилегией фазы
   допуска (§3: контроль честности — пара «раскрытие + одобрение»)."""
from dataclasses import dataclass

from job_machine.discovery.geo import classify_location
from job_machine.triage.gates import (
    CandidateProfile, _allowed_regions, _kw_present, band_of, families_of)
from job_machine.triage.gates_config import GateConfig
from job_machine.triage.models import HANDS_ON_LEVELS, TriageVerdict
from job_machine.triage.score_config import ScoreConfig

_BAND_ORDER = ["A", "B", "C", "D"]
_CAP_BAND = "C"


@dataclass
class FitScore:
    score: int                    # 0–100 композит
    band: str                     # A/B/C/D
    vectors: dict                 # семь векторов, все всегда присутствуют
    weights: dict
    confidence: float             # 0–1 (доля не-unknown требований)
    capped_by: list               # векторы, срезавшие бэнд мягким порогом
    flags: list
    version: str

    def breakdown(self) -> dict:
        return {"vectors": self.vectors, "weights": self.weights,
                "confidence": round(self.confidence, 3),
                "capped_by": list(self.capped_by), "flags": self.flags}


def _requirements_vector(verdict, cfg):
    """(score, confidence). Вес требования — must=1.0 / nice=0.5; кредит — по статусу.
    Пустой список → 0: отсутствие разбора больше НЕ исключает вектор из знаменателя
    (именно так 577 строк получали band A).

    ВНИМАНИЕ про confidence на пустом списке. Это доля НЕ-unknown среди РАЗОБРАННЫХ
    требований, а не «уверенность в оценке». На пустом списке отбраковывать нечего,
    поэтому формально она 1.0 — но знаем мы при этом ноль. Не полагаться на неё как
    на признак качества разбора: за этот случай отвечает отдельный флаг
    requirements_not_parsed (compute_fit_score) плюс мягкий порог, роняющий бэнд."""
    reqs = verdict.hard_requirements
    if not reqs:
        return 0, 1.0
    pts, iw = cfg.status_points, cfg.importance_weights
    num = sum(iw.get(r.importance, 1.0) * pts.get(r.status, 0) for r in reqs)
    den = sum(iw.get(r.importance, 1.0) for r in reqs) or 1.0
    unknown = sum(1 for r in reqs if r.status == "unknown")
    return round(num / den), 1.0 - unknown / len(reqs)


def _hands_on_vector(verdict, profile, cfg):
    """Штраф ТОЛЬКО за недобор практики (решение владельца 2026-08-15): роль требует
    больше рук, чем есть у кандидата. Перебор («перерос роль») не наказывается."""
    req = verdict.hands_on.required_level
    cand = profile.hands_on_band
    if req not in HANDS_ON_LEVELS or cand not in HANDS_ON_LEVELS:
        return 0
    d = max(0, HANDS_ON_LEVELS.index(req) - HANDS_ON_LEVELS.index(cand))
    return cfg.hands_on_scale.get(d, 0)


def _domain_vector(verdict, profile, cfg):
    """Сверка ЯРЛЫКОВ из закрытого перечня (models.INDUSTRY_ENUM), не свободного текста —
    иначе вектор недетерминирован. Пустой профиль доменов = неизвестность на стороне
    кандидата → 0, а не «не совпало»."""
    industry = verdict.domain.industry
    if not industry:
        return 0
    cand = {d.strip().lower() for d in profile.domains if d.strip()}
    if not cand:
        return 0
    if industry in cand:
        return cfg.domain_points["match"]
    if any(a in cand for a in cfg.domain_adjacency.get(industry, [])):
        return cfg.domain_points["adjacent"]
    return cfg.domain_points["other"]


def _stack_vector(verdict, profile, cfg):
    """Доля требуемых технологий, подтверждённых cloud_skill кандидата.
    required=False — ФАКТ «стек не требуется» → 100; required=None или пустой список
    при required=True — неизвестность → 0 (§4.1 спеки)."""
    if verdict.stack.required is False:
        return 100
    techs = {t.strip().lower() for t in verdict.stack.technologies if t.strip()}
    if not techs:
        return 0
    have = {s.strip().lower() for s in profile.skills if s.strip()}
    return round(100 * len(techs & have) / len(techs))


def _role_family_vector(title, profile, gate_cfg):
    """100 — пересечение семей title и кандидата; 50 — фолбэк по ГРАНИЦАМ СЛОВ
    (не голый substring: 'qa' не должна ловиться в 'qatar'); 0 — нет совпадения либо
    title не распознан. Множители семей убраны: на векторе с весом 0.10 они ничего
    не решали, а искажали семантику балла (YAGNI)."""
    title_fams = families_of(title, gate_cfg)
    cand_fams = set()
    for r in profile.roles:
        cand_fams |= families_of(r, gate_cfg)
    if title_fams & cand_fams:
        return 100
    low = (title or "").lower()
    if any(_kw_present(r.strip().lower(), low) for r in profile.roles if r.strip()):
        return 50
    return 0


def _seniority_vector(title, profile, gate_cfg, score_cfg):
    """Расстояние бандов по шкале конфига. Неизвестный банд с любой стороны → 0
    (fit-1 исключал ось из знаменателя, fit-2 этого не делает)."""
    if not profile.seniority_band or profile.seniority_band not in gate_cfg.level_bands:
        return 0
    vac = band_of(title, gate_cfg)
    if vac is None:
        return 0
    d = abs(gate_cfg.level_bands.index(vac)
            - gate_cfg.level_bands.index(profile.seniority_band))
    return score_cfg.seniority_scale.get(d, 0)


def _geo_mode_vector(location, profile, gate_cfg, score_cfg, work_mode=None):
    """Глобальный remote → 100; remote внутри разрешённого региона → 90; hybrid → 70;
    onsite → 60; нераспознанная локация → 0. Гео больше НЕ блокер — жёсткий случай
    (обязательный онсайт вне доступных стран) забрала фаза допуска."""
    low = (location or "").lower()
    if any(t in low for t in gate_cfg.geo_global_tokens):
        return score_cfg.geo_points["global_remote"]
    region = classify_location(location)
    if region == "unknown" or region not in _allowed_regions(profile, gate_cfg):
        return 0
    if work_mode == "remote":
        return score_cfg.geo_points["regional_remote"]
    if work_mode == "hybrid":
        return score_cfg.geo_points["hybrid"]
    if work_mode == "onsite":
        return score_cfg.geo_points["onsite"]
    return 0


def _band(score, thresholds):
    if score >= thresholds["A"]:
        return "A"
    if score >= thresholds["B"]:
        return "B"
    if score >= thresholds["C"]:
        return "C"
    return "D"


def compute_fit_score(verdict: TriageVerdict, title, location,
                      profile: CandidateProfile, gate_cfg: GateConfig,
                      score_cfg: ScoreConfig, work_mode: str | None = None) -> FitScore:
    req_score, confidence = _requirements_vector(verdict, score_cfg)
    vectors = {
        "requirements": req_score,
        "hands_on": _hands_on_vector(verdict, profile, score_cfg),
        "domain": _domain_vector(verdict, profile, score_cfg),
        "stack": _stack_vector(verdict, profile, score_cfg),
        "role_family": _role_family_vector(title, profile, gate_cfg),
        "seniority": _seniority_vector(title, profile, gate_cfg, score_cfg),
        "geo_mode": _geo_mode_vector(location, profile, gate_cfg, score_cfg, work_mode),
    }
    weights = score_cfg.weights
    w_total = sum(weights.get(k, 0.0) for k in vectors) or 1.0
    composite = round(sum(v * weights.get(k, 0.0) for k, v in vectors.items()) / w_total)
    composite = max(0, min(100, composite))

    band = _band(composite, score_cfg.band_thresholds)
    capped_by = [k for k, floor in score_cfg.soft_floors.items()
                 if vectors.get(k, 0) < floor]
    if capped_by and _BAND_ORDER.index(band) < _BAND_ORDER.index(_CAP_BAND):
        band = _CAP_BAND

    flags = []
    if not verdict.hard_requirements:
        flags.append("requirements_not_parsed")
    if confidence < score_cfg.confidence_floor:
        flags.append("low_confidence")

    return FitScore(score=composite, band=band, vectors=vectors,
                    weights=dict(weights), confidence=confidence,
                    capped_by=capped_by, flags=flags, version=score_cfg.version)
