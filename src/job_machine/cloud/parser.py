"""Детерминированный парсер experience-cloud.md: три pipe-таблицы под
## Positions / ## Achievements / ## Skills. Ячейки не содержат '|'."""

from job_machine.cloud.models import (
    CloudAchievement, CloudPosition, CloudSkill, ExperienceCloud,
)


def _row_cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _is_separator(cells: list[str]) -> bool:
    return bool(cells) and all(set(c) <= set("-: ") and c for c in cells)


def _table_after(lines: list[str], header: str) -> list[dict]:
    """Строки-словари таблицы, идущей сразу за заголовком '## <header>'."""
    out: list[dict] = []
    i = 0
    while i < len(lines) and lines[i].strip() != f"## {header}":
        i += 1
    i += 1
    while i < len(lines) and not lines[i].lstrip().startswith("|"):
        if lines[i].strip().startswith("## "):
            return out
        i += 1
    if i >= len(lines):
        return out
    cols = _row_cells(lines[i]); i += 1
    if i < len(lines) and _is_separator(_row_cells(lines[i])):
        i += 1
    while i < len(lines) and lines[i].lstrip().startswith("|"):
        cells = _row_cells(lines[i]); i += 1
        if len(cells) < len(cols):
            cells += [""] * (len(cols) - len(cells))
        out.append({cols[j]: cells[j] for j in range(len(cols))})
    return out


def parse_experience_cloud(md: str) -> ExperienceCloud:
    lines = md.splitlines()
    positions = [CloudPosition(pid=r["pid"], company=r["company"], title=r["title"],
                               start=r["start"], end=r["end"],
                               location=r.get("location", ""), summary=r.get("summary", ""))
                 for r in _table_after(lines, "Positions") if r.get("pid")]
    achievements = [CloudAchievement(aid=r["aid"], pid=r["pid"], text=r["text"],
                                     metric=r.get("metric", ""), status=r.get("status", ""),
                                     claims=r.get("claims", ""), safe_use=r.get("safe_use", ""))
                    for r in _table_after(lines, "Achievements") if r.get("aid")]
    skills = [CloudSkill(name=r["name"], category=r.get("category", ""),
                         framing=r.get("framing", ""), evidence=r.get("evidence", ""),
                         safe_use=r.get("safe_use", ""))
              for r in _table_after(lines, "Skills") if r.get("name")]
    return ExperienceCloud(positions=positions, achievements=achievements, skills=skills)
