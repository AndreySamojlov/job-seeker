"""Парсер таблицы application-answer-vault (.md) → list[AnswerRecord]."""
from job_machine.package.models import AnswerRecord

_STATES = {"locked", "blocked", "optional-policy"}


def parse_answer_vault(markdown: str) -> list[AnswerRecord]:
    rows: list[AnswerRecord] = []
    for line in (markdown or "").splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 3:
            continue
        field, value, state = cells[0], cells[1], cells[2].lower()
        rule = cells[3] if len(cells) > 3 else ""
        if state not in _STATES:
            continue  # заголовок, разделитель, мусор
        rows.append(AnswerRecord(field=field, value=value, state=state, rule=rule))
    return rows
