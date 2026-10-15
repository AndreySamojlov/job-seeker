"""Разовый ре-триаж исторических квик-скипов (спека 2026-07-02 §4; адаптировано
под пер-кандидатный триаж-леджер, Task 8).

Пер-кандидатно (candidate_id): находит вакансии, у которых в triage_result для
этого кандидата стоит verdict='skip', пришедший из квик-скипа (событие
vacancy.quick_skipped с reason work_mode|title_mismatch, БЕЗ последующего
LLM vacancy.skipped для того же кандидата), чей тайтл проходит ТЕКУЩИЙ ролевой
фильтр кандидата (_role_matches, роли из search_profile; Task 8). "Спасение" —
удаление строки triage_result(candidate_id, vacancy_id), чтобы вакансия снова
попала в pull_untriaged_for_candidate (LLM-триаж). DELETE guard'ится
verdict='skip': между SELECT-выборкой и DELETE параллельный LLM-триаж
теоретически мог успеть переписать вердикт (например, на 'apply') — guard не
даёт снести уже принятое LLM-решение, откатывая только ещё не тронутый
квик-скип (не устраняет гонку целиком: LLM тоже может прийти к 'skip', тогда
DELETE всё равно применится — но наихудший случай, потеря 'apply', исключён).
Общий vacancy.state/vacancy_status НЕ трогаем — вакансия остаётся общим пулом
для других кандидатов (в русле record_quick_skip/apply_verdict, Task 8).
Не трогает: LLM-скипы этого кандидата (есть vacancy.skipped с его candidate_id),
вакансии, по которым у этого кандидата уже есть заявка.
Каждый возврат — событие vacancy.requeued (audit append-only).

Запуск: .venv/Scripts/python.exe scripts/requeue_quick_skips.py [--apply] [--candidate-id ID]
Без --apply — dry-run (только печать). --candidate-id по умолчанию "andrey-s".
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from job_machine import audit  # noqa: E402
from job_machine.db.connection import connect  # noqa: E402
from job_machine.triage import store as triage_store  # noqa: E402
from job_machine.triage.gates import (  # noqa: E402
    geo_skip, level_band_skip, role_family_skip)
from job_machine.triage.gates_config import load_gate_config  # noqa: E402
from job_machine.triage.service import _role_matches  # noqa: E402

# event.entity_id и vacancy.vacancy_id — оба uuid (db/migrations/0001_core_schema.sql),
# прямой джойн без каста корректен.
# Вакансия может иметь несколько vacancy.quick_skipped-событий для одного кандидата
# (повторные verify/triage-прогоны с разными reason) — группируем по vacancy_id,
# чтобы не размножать её в выдаче; reason берём последний по created_at (для аудита).
_SELECT = """
select v.vacancy_id, v.title, v.location,
       (array_agg(e.payload_json->>'reason' order by e.created_at desc))[1] as reason
from vacancy v
join triage_result tr on tr.vacancy_id = v.vacancy_id and tr.candidate_id = %(cid)s
join event e on e.entity_id = v.vacancy_id
where tr.verdict = 'skip'
  and e.event_type = 'vacancy.quick_skipped'
  and e.payload_json->>'candidate_id' = %(cid)s
  and e.payload_json->>'reason' in ('work_mode', 'title_mismatch')
  and not exists (select 1 from application a
                  where a.vacancy_id = v.vacancy_id and a.candidate_id = %(cid)s)
  and not exists (select 1 from event e2
                  where e2.entity_id = v.vacancy_id
                    and e2.event_type = 'vacancy.skipped'
                    and e2.payload_json->>'candidate_id' = %(cid)s)
group by v.vacancy_id, v.title, v.location
"""

_DELETE_TRIAGE_RESULT = """
delete from triage_result where candidate_id = %s and vacancy_id = %s and verdict = 'skip'
"""


def requeue(conn, candidate_id: str = "andrey-s", dry_run: bool = True) -> list[str]:
    """Вернуть список спасённых vacancy_id (в dry-run — кандидатов) для candidate_id.

    Реанимируем только квик-скипы (work_mode|title_mismatch), чей title проходит
    _role_matches И которые НЕ зарезал бы ни один детерминированный гейт (role_family/
    level_band/geo). Иначе спасение бессмысленно: следующий build_triage_inputs тут же
    снова их скипнет. Dedup-гейт здесь опускаем — он требует батчевого PassState и
    относится к дублям внутри одного pull, а не к пер-item реанимации."""
    roles = triage_store.load_candidate_roles(conn, candidate_id)
    profile = triage_store.load_candidate_profile(conn, candidate_id)
    cfg = load_gate_config()
    with conn.cursor() as cur:
        cur.execute(_SELECT, {"cid": candidate_id})
        rows = cur.fetchall()
    rescued: list[str] = []
    for vid, title, location, reason in rows:
        if not _role_matches(title, roles):
            continue
        if (role_family_skip(title, profile, cfg)
                or level_band_skip(title, profile, cfg)
                or geo_skip(location, profile, cfg)):
            continue
        rescued.append(str(vid))
        if dry_run:
            continue
        with conn.cursor() as cur:
            cur.execute(_DELETE_TRIAGE_RESULT, (candidate_id, vid))
        audit.emit_event(conn, "vacancy", vid, "vacancy.requeued",
                         {"reason": "prefilter_rescue", "prior_reason": reason,
                          "title": title, "candidate_id": candidate_id})
    if not dry_run:
        conn.commit()
    return rescued


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="применить (иначе dry-run)")
    ap.add_argument("--candidate-id", default="andrey-s",
                    help="кандидат, чьи роли используются для фильтра (default: andrey-s)")
    args = ap.parse_args()
    conn = connect()
    try:
        rescued = requeue(conn, args.candidate_id, dry_run=not args.apply)
    finally:
        conn.close()
    mode = "APPLIED" if args.apply else "DRY-RUN"
    print(f"[{mode}] спасено: {len(rescued)}")
    for vid in rescued:
        print(vid)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
