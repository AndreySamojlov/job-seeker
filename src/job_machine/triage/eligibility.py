"""[POLICY] Фаза допуска (fit-2). Чистая функция, без I/O.

Блокирует заявку ТОЛЬКО по позитивно установленному факту и ТОЛЬКО по трём из пяти
категорических исключений §3 CLAUDE.md (mandatory_language / clearance_or_citizenship /
onsite_location) — новой политики не вводится, формализуется действующая.

Ключевая асимметрия: НЕИЗВЕСТНОСТЬ ЗДЕСЬ НЕ БЛОКИРУЕТ, а уходит в material_unknowns и
раскрывается владельцу. Правило «неизвестно = 0» действует только в фазе пригодности,
где оно про баллы, а не про приговор: иначе любая вакансия с неполным JD получала бы
skip, что прямо против §3 (контроль честности — пара «раскрытие + одобрение»)."""
from dataclasses import dataclass, field

from job_machine.discovery.geo import classify_location
from job_machine.triage.gates import CandidateProfile, _allowed_regions
from job_machine.triage.gates_config import GateConfig
from job_machine.triage.models import TriageVerdict


@dataclass
class EligibilityResult:
    blocked: bool = False
    category: str | None = None      # значение skip_category при блокировке
    reason: str | None = None        # человекочитаемое обоснование для аудита
    unknowns: list[str] = field(default_factory=list)

    def payload(self) -> dict:
        return {"blocked": self.blocked, "category": self.category,
                "reason": self.reason, "unknowns": list(self.unknowns)}


def _language_block(verdict, profile, unknowns) -> tuple[str, str] | None:
    """mandatory тристабилен: True — обязателен, False — факт «не обязателен»,
    None — неизвестно. Блокируем только по True; None раскрываем владельцу."""
    have = {lang.strip().lower() for lang in profile.languages if lang.strip()}
    for req in verdict.eligibility.required_languages:
        if req.language.strip().lower() in have:
            continue
        level = f" ({req.level})" if req.level else ""
        if req.mandatory is True:
            return ("mandatory_language",
                    f"Posting requires {req.language}{level}; candidate's profile "
                    f"lists {sorted(have) or 'no languages'}.")
        if req.mandatory is None:
            unknowns.append(
                f"Posting mentions {req.language}{level}, which the candidate does "
                f"not list; whether it is mandatory is not stated.")
    return None


def _authorization_block(verdict, unknowns) -> tuple[str, str] | None:
    wa = verdict.eligibility.work_authorization
    if wa.requires_clearance is True:
        return ("clearance_or_citizenship",
                "Posting requires security clearance or citizenship.")
    if wa.requires_local_right is True:
        if wa.sponsorship_offered is False:
            return ("clearance_or_citizenship",
                    "Posting requires existing local right to work and states that "
                    "sponsorship is not offered.")
        if wa.sponsorship_offered is None:
            unknowns.append("Posting requires local right to work; sponsorship "
                            "availability is not stated.")
    return None


def _onsite_block(verdict, profile, cfg, unknowns) -> tuple[str, str] | None:
    onsite = verdict.eligibility.onsite
    if onsite.onsite_required is not True:
        return None
    if onsite.relocation_supported is True:
        return None
    if not onsite.city:
        unknowns.append("Posting requires onsite presence but does not state the "
                        "location.")
        return None
    region = classify_location(onsite.city)
    if region == "unknown":
        unknowns.append(f"Posting requires onsite presence in {onsite.city}; the "
                        f"region could not be resolved.")
        return None
    if region in _allowed_regions(profile, cfg):
        return None
    # Молчание про релокацию — НЕ отказ в ней. Блокируем только когда факт «релокации
    # нет» установлен позитивно (False); при None раскрываем владельцу, как и во всех
    # остальных ветках модуля. Иначе типовая вакансия «онсайт в городе X», не сказавшая
    # про релокацию ни слова, отбрасывалась бы молча — ровно то, что инвариант запрещает.
    if onsite.relocation_supported is None:
        unknowns.append(
            f"Posting requires onsite presence in {onsite.city} ({region}), outside "
            f"the candidate's available regions; relocation support is not stated.")
        return None
    return ("onsite_location",
            f"Posting requires onsite presence in {onsite.city} ({region}), outside "
            f"the candidate's available regions, with no relocation support.")


def check_eligibility(verdict: TriageVerdict, profile: CandidateProfile,
                      cfg: GateConfig) -> EligibilityResult:
    """Первая фаза fit-2. Блокировка → верхний уровень ставит verdict='skip' с этой
    категорией и НЕ считает скор пригодности (fit_score остаётся NULL)."""
    unknowns: list[str] = []
    for block in (_language_block(verdict, profile, unknowns),
                  _authorization_block(verdict, unknowns),
                  _onsite_block(verdict, profile, cfg, unknowns)):
        if block is not None:
            category, reason = block
            return EligibilityResult(blocked=True, category=category, reason=reason,
                                     unknowns=unknowns)
    return EligibilityResult(unknowns=unknowns)
