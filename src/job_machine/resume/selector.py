"""Детерминированный отбор и скоринг строк облака под требования вакансии. Без LLM/I-O.

Честность: позиции/тайтлы — из cloud_position, буллеты — из cloud_achievement (aid),
скиллы — verbatim из cloud_skill. Ничего не выдумывается; только отбор и порядок.
"""
import re

from job_machine.cloud.models import ExperienceCloud
from job_machine.resume.headline import headline_for_role
from job_machine.resume.models import (
    PhrasingRequest, ResumeSelection, SelectedBullet, SelectedPosition, SkillGroup,
)

_STOP = {"and", "the", "for", "with", "that", "this", "from", "into", "our", "you",
         "your", "are", "was", "has", "have", "had", "not", "but", "all", "any",
         "per", "via", "across", "under", "over", "lead", "leader"}
RESERVED_SKILL_CATEGORIES = ["certification", "education", "language"]
_DELIVERY = {"delivery", "engineering", "manager", "management", "program", "director"}
_QA = {"qa", "quality", "test", "testing", "sdet"}


def _terms(text: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", (text or "").lower())
            if len(t) >= 3 and t not in _STOP}


def _is_artifact(text: str) -> bool:
    """Пустой / «—»-«-» / только пунктуация текст буллета → артефакт, не отбираем."""
    stripped = (text or "").strip()
    if not stripped:
        return True
    return not re.search(r"[0-9a-zA-Zа-яёА-ЯЁ]", stripped)


def _claim_ids(text: str) -> set[str]:
    return set(re.findall(r"c-\d+", (text or "").lower()))


def _req_profile(hard_requirements: list[dict]) -> tuple[set[str], set[str]]:
    terms: set[str] = set()
    claims: set[str] = set()
    for r in hard_requirements or []:
        terms |= _terms(r.get("requirement", ""))
        for cid in r.get("evidence_claim_ids", []) or []:
            claims.add(str(cid).lower())
    return terms, claims


def _score(ach, req_terms: set[str], req_claims: set[str]) -> int:
    overlap = len(_terms(f"{ach.text} {ach.metric}") & req_terms)
    boost = 2 * len(_claim_ids(ach.claims) & req_claims)
    return overlap + boost


def _choose_headline(positions: list[SelectedPosition], role: str) -> str:
    if not positions:
        return ""
    title = positions[0].title
    halves = [h.strip() for h in title.split("/")]
    if len(halves) == 2:
        role_t = _terms(role)
        if (role_t & _DELIVERY) and not (role_t & _QA):
            halves = [halves[1], halves[0]]   # same words, delivery half first
    return " / ".join(halves)


def _skill_score(s, req_terms: set[str]) -> int:
    return len(_terms(s.name) & req_terms)


def _skill_groups(skills, req_terms: set[str], max_core: int = 12) -> list[SkillGroup]:
    by_cat: dict[str, list] = {}
    for s in skills:
        by_cat.setdefault(s.category or "skill", []).append(s)

    # Любая категория, не входящая в RESERVED_SKILL_CATEGORIES ("skill", "qa", "data",
    # "process", "tools", ...) — skill-подобный бакет: тот же req_terms-скоринг и
    # усечение max_core, что раньше было зарезервировано только за буквальным "skill".
    skill_like = [c for c in by_cat if c not in RESERVED_SKILL_CATEGORIES]
    skill_like.sort(key=lambda c: (
        -max((_skill_score(s, req_terms) for s in by_cat[c]), default=0), c))
    ordered_cats = skill_like + [c for c in RESERVED_SKILL_CATEGORIES if c in by_cat]

    groups: list[SkillGroup] = []
    for cat in ordered_cats:
        items = by_cat[cat]
        if cat in skill_like:
            items = sorted(items, key=lambda s: (-_skill_score(s, req_terms), s.name))[:max_core]
        else:
            items = sorted(items, key=lambda s: s.name)
        rendered = [f"{s.name} — {s.framing}" if not _is_artifact(s.framing) else s.name
                    for s in items]
        if rendered:
            groups.append(SkillGroup(category=cat, items=rendered))
    return groups


def build_selection(application_id: str, role: str, hard_requirements: list[dict],
                    cloud: ExperienceCloud, candidate_name: str = "", candidate_id: str = "",
                    max_bullets: int = 4) -> ResumeSelection:
    req_terms, req_claims = _req_profile(hard_requirements)
    ach_by_pid: dict[str, list] = {}
    for a in cloud.achievements:
        if _is_artifact(a.text):        # §4.4: пустой/«—» буллет не отбираем
            continue
        ach_by_pid.setdefault(a.pid, []).append(a)
    positions: list[SelectedPosition] = []
    have_ach = [p for p in cloud.positions if p.pid in ach_by_pid]
    have_ach.sort(key=lambda p: p.start, reverse=True)   # recent first (ISO YYYY-MM strings)
    for p in have_ach:
        ranked = sorted(ach_by_pid[p.pid],
                        key=lambda a: (-_score(a, req_terms, req_claims), a.aid))[:max_bullets]
        ranked = sorted(ranked, key=lambda a: a.aid)      # stable display order
        bullets = [SelectedBullet(aid=a.aid, source_text=a.text, source_metric=a.metric,
                                  safe_use=a.safe_use) for a in ranked]
        positions.append(SelectedPosition(pid=p.pid, company=p.company, title=p.title,
                                          start=p.start, end=p.end, location=p.location,
                                          bullets=bullets))
    headline = headline_for_role(candidate_id, role, fallback=_choose_headline(positions, role))
    return ResumeSelection(
        application_id=application_id, headline=headline,
        candidate_name=candidate_name,
        positions=positions, skill_groups=_skill_groups(cloud.skills, req_terms))


def phrasing_request(selection: ResumeSelection, jd_summary: str = "") -> PhrasingRequest:
    bullets = [{"aid": b.aid, "source_text": b.source_text, "source_metric": b.source_metric}
               for p in selection.positions for b in p.bullets]
    return PhrasingRequest(application_id=selection.application_id,
                           headline=selection.headline, jd_summary=jd_summary,
                           bullets=bullets)
