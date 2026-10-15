"""Append-only запись поданных заявок в audit/*.csv (канон §8).

Строка деривируется ИЗ БД (событие application.submitted — единственный триггер;
submitted_at = created_at события) — свободные значения вызывающего в CSV не
попадают (аудит 02.07: fail-open record_outcome). xlsx-канон НЕ трогаем.
"""
import csv
from pathlib import Path

_FIELDS = ["application_id", "company", "role", "url", "status",
           "confirmation_url", "submitted_at"]
# Пустые обязательные поля = мусорная строка; фейлим до записи (fail-closed).
# company НЕ обязателен: vacancy.company nullable в схеме — отсутствие названия
# компании не должно терять реальный сабмит из аудита (ревью среза).
_REQUIRED = ("application_id", "url", "submitted_at")


def append_submission(csv_path: str, record: dict) -> None:
    """Дописать строку в submissions.csv, создав файл+заголовок при первом вызове."""
    missing = [k for k in _REQUIRED if not str(record.get(k) or "").strip()]
    if missing:
        raise ValueError(f"submission record missing required fields: {missing}")
    path = Path(csv_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_FIELDS, extrasaction="ignore")
        if is_new:
            writer.writeheader()
        writer.writerow({k: record.get(k, "") for k in _FIELDS})


def _existing_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    with path.open(newline="", encoding="utf-8") as f:
        return {r.get("application_id", "") for r in csv.DictReader(f)}


def load_submitted_rows(conn, application_id=None) -> list[dict]:
    """Поданные заявки ИЗ БД: событие application.submitted ⋈ application ⋈ vacancy."""
    sql = (
        "select a.application_id, v.company, v.title, "
        "coalesce(a.final_apply_url, v.canonical_url), a.state, "
        "e.payload_json->>'confirmation_url', e.created_at "
        "from application a "
        "join vacancy v on v.vacancy_id = a.vacancy_id "
        "join lateral (select payload_json, created_at from event "
        "  where entity_id = a.application_id "
        "  and event_type='application.submitted' "
        "  order by created_at desc limit 1) e on true ")
    params: tuple = ()
    if application_id is not None:
        sql += "where a.application_id=%s "
        params = (application_id,)
    sql += "order by e.created_at"
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    return [{
        "application_id": str(r[0]), "company": r[1] or "", "role": r[2] or "",
        "url": r[3] or "", "status": r[4] or "",
        "confirmation_url": r[5] or "",
        "submitted_at": r[6].isoformat(),
    } for r in rows]


def sync_submissions(conn, csv_path: str, application_id=None) -> dict:
    """Append-only синк CSV из БД: дописываются только отсутствующие application_id.

    Существующие строки (включая исторический мусор) НЕ переписываются и НЕ
    удаляются (§8 append-only); коррекция потерянных сабмитов = дозапись."""
    rows = load_submitted_rows(conn, application_id)
    existing = _existing_ids(Path(csv_path))
    appended, invalid = [], []
    for row in rows:
        if row["application_id"] in existing:
            continue
        try:
            append_submission(csv_path, row)
        except ValueError:
            # Невалидная строка (нет URL и т.п.) не прерывает батч: append-only
            # синк обязан дописать остальные сабмиты (ревью среза).
            invalid.append(row["application_id"])
            continue
        appended.append(row["application_id"])
    return {"appended": len(appended), "matched": len(rows),
            "skipped": len(rows) - len(appended) - len(invalid),
            "invalid": invalid, "application_ids": appended}
