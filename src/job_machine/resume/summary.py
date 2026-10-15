"""Детерминированный Summary: полный стаж + headline + топ-скиллы под вакансию. Без LLM/вымысла.

Тенюр = span от min(start-year) по всем позициям до max(end-year); 'present' → текущий год
(честно: стаж по сей день). Годы берутся из ВСЕГО облака, а не только из отображённых
позиций с буллетами (§3-честность: не приписываем весь span конкретной роли/лидерству —
early-career годы входят в стаж, но роль несёт headline).

Company — самая свежая позиция по `start` (лексикографическое сравнение ISO YYYY-MM
строк работает как хронологическое, тот же приём, что и в selector.py).

Core strengths — verbatim топ-2 строки из объединения всех skill-подобных категорий
skill_groups (т.е. всех, кроме RESERVED_SKILL_CATEGORIES — certification/education/
language; см. selector.py), в порядке самих групп (те же уже посчитанные под требования
вакансии данные, что скорят буллеты/скиллы — не пересчитываем), с фильтром хеджированного
framing (см. `_WEAK_FRAMING_MARKERS`): скилл
с framing вроде «Fundamentals only»/«…familiarity» честен, но самоподрывает заголовок
«Core strengths», если попадает туда просто по совпадению ключевых слов с вакансией.
Секция Skills/`selector.py` не трогается — там такие framing уместны и остаются как есть.
Если после фильтра сильных скиллов не осталось — клауза «Core strengths» опускается
целиком, а не заполняется хеджем (§3: не заявляем сильную сторону там, где её нет).
Отсутствующие компоненты (headline/company/skill_groups) молча опускаются из фразы
(§3: отсутствующее не заявляем), а не рендерятся пустыми.
"""
from datetime import date

from job_machine.cloud.models import ExperienceCloud
from job_machine.resume.models import SkillGroup
from job_machine.resume.selector import RESERVED_SKILL_CATEGORIES

_WEAK_FRAMING_MARKERS = ("fundamentals only", "familiarity", "project-context")


def _is_weak_framing(item: str) -> bool:
    low = item.lower()
    return any(m in low for m in _WEAK_FRAMING_MARKERS)


def _year(s: str) -> int | None:
    s = (s or "").strip()
    if s.lower() in {"present", "current", "now"}:
        return date.today().year
    return int(s[:4]) if len(s) >= 4 and s[:4].isdigit() else None


def build_summary(cloud: ExperienceCloud, headline: str,
                  skill_groups: list[SkillGroup] | None = None) -> str:
    skill_groups = skill_groups or []
    starts = [y for p in cloud.positions if (y := _year(p.start)) is not None]
    ends = [y for p in cloud.positions if (y := _year(p.end)) is not None]
    if not starts:
        return ""
    span = max(ends or [max(starts)]) - min(starts)
    sentence = f"{span}+ years in technology"

    dated = [p for p in cloud.positions if p.start]
    recent = max(dated, key=lambda p: p.start) if dated else None
    if headline and recent is not None and recent.company:
        sentence += f", most recently as {headline} at {recent.company}"
    sentence += "."

    skill_like_items = [i for g in skill_groups if g.category not in RESERVED_SKILL_CATEGORIES
                        for i in g.items]
    if skill_like_items:
        strong = [i for i in skill_like_items if not _is_weak_framing(i)]
        top = strong[:2]
        if top:
            sentence += " Core strengths: " + ", ".join(top) + "."
    return sentence
