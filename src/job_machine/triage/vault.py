import re

from job_machine.triage.models import ClaimRecord

_CLAIM_ID = re.compile(r"^C-\d+$")
_STATUS = {"verified", "approximate", "unknown"}


def _cells(line: str) -> list[str]:
    # markdown-строка таблицы: "| a | b | c |" → ["a","b","c"]
    return [c.strip() for c in line.strip().strip("|").split("|")]


def parse_vault(markdown: str) -> list[ClaimRecord]:
    """Извлечь записи из markdown-таблицы Claims. Берём только строки, где первая
    ячейка — идентификатор claim'а (C-NNN); прочие таблицы (STAR и т.п.) игнорируются."""
    out: list[ClaimRecord] = []
    for line in markdown.splitlines():
        if "|" not in line:
            continue
        cells = _cells(line)
        if len(cells) < 3 or not _CLAIM_ID.match(cells[0]):
            continue
        status = cells[2].lower()
        if status not in _STATUS:
            continue
        out.append(ClaimRecord(
            claim_id=cells[0],
            claim_text=cells[1],
            status=status,
            proof=cells[3] if len(cells) > 3 else None,
            safe_use=cells[4] if len(cells) > 4 else None,
        ))
    return out
