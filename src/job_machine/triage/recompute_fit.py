"""CLI: пересчитать fit-score по сохранённым в triage_result вердиктам, без LLM.
Применять после смены весов/порогов в config/fit_score.json.
Usage: python -m job_machine.triage.recompute_fit --candidate-id <id> [--vacancy-id <id>]"""
import argparse
import uuid

from psycopg.types.json import Json

from job_machine import audit
from job_machine.triage.gates_config import load_gate_config
from job_machine.triage.models import HardRequirementMatch, TriageVerdict
from job_machine.triage.score_config import load_score_config
from job_machine.triage.scoring import compute_fit_score
from job_machine.triage.store import (
    application_id_for, load_candidate_profile, _load_vacancy_axes)


def recompute(conn, candidate_id: str, vacancy_id=None) -> int:
    """Пересчитать fit-score всех (или одной) строк triage_result кандидата. Возвращает
    число обновлённых строк. Коммит per-item."""
    gate_cfg, score_cfg = load_gate_config(), load_score_config()
    profile = load_candidate_profile(conn, candidate_id)
    q = ("select vacancy_id, verdict, fit_summary, hard_requirements, "
         "material_unknowns, overclaim_risks, eligibility, fit_facts from triage_result "
         "where candidate_id=%s "
         # Без разбора требований скорить нечего: именно такие строки (gate-skip)
         # получали band A из одних только title и локации.
         "and hard_requirements is not null and jsonb_array_length(hard_requirements) > 0")
    params = [candidate_id]
    if vacancy_id:
        q += " and vacancy_id=%s"
        params.append(uuid.UUID(str(vacancy_id)))
    with conn.cursor() as cur:
        cur.execute(q, params)
        rows = cur.fetchall()
    n = 0
    for vid, verdict, fit_summary, hard_reqs, munk, ocr, elig_row, facts in rows:
        # Блокировка допуска — скор пригодности не считается вовсе (store.apply_verdict
        # держит то же правило): число для вакансии, куда кандидата не пустят, вводит
        # в заблуждение в очереди и отчётах.
        if (elig_row or {}).get("blocked"):
            continue
        # Факты v2 восстанавливаются из снимка fit_facts. Без них векторы
        # hands_on/domain/stack молча обнулялись бы, и пересчёт при тех же весах
        # ронял бы бэнд вместо того, чтобы его воспроизвести (ревью 2026-08-15).
        v = TriageVerdict(
            vacancy_id=str(vid), verdict=verdict, fit_summary=fit_summary or "",
            hard_requirements=[HardRequirementMatch(**r) for r in (hard_reqs or [])],
            material_unknowns=list(munk or []), overclaim_risks=list(ocr or []),
            **{k: val for k, val in (facts or {}).items()
               if k in ("eligibility", "domain", "stack", "hands_on") and val})
        title, location, work_mode = _load_vacancy_axes(conn, vid)
        fit = compute_fit_score(v, title, location, profile, gate_cfg, score_cfg,
                                work_mode=work_mode)
        with conn.cursor() as cur:
            cur.execute(
                "update triage_result set fit_score=%s, fit_band=%s, fit_breakdown=%s, "
                "fit_score_version=%s, capped_by=%s "
                "where candidate_id=%s and vacancy_id=%s",
                (fit.score, fit.band, Json(fit.breakdown()), fit.version,
                 list(fit.capped_by), candidate_id, vid))
        aid = application_id_for(conn, candidate_id, vid)
        etype, eid = ("application", aid) if aid else ("vacancy", vid)
        audit.emit_event(conn, etype, eid, "application.fit_scored",
                         {"fit_score": fit.score, "fit_band": fit.band,
                          "candidate_id": candidate_id, "version": fit.version})
        conn.commit()
        n += 1
    return n


def main() -> None:
    from job_machine.db.connection import connect
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidate-id", required=True)
    ap.add_argument("--vacancy-id", default=None)
    args = ap.parse_args()
    conn = connect()
    try:
        n = recompute(conn, args.candidate_id, args.vacancy_id)
        print(f"recomputed {n} row(s)")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
