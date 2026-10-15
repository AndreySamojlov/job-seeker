"""Оркестрация сборки пакетов. Детерминированно, без браузера/submit/LLM."""
from job_machine import provenance
from job_machine.package import artifacts, store
from job_machine.package.answer_resolve import merge_answers
from job_machine.package.builder import build_package
from job_machine.package.models import PackageInput
from job_machine.package.summary import render_summary


def run_package_build(conn, base_dir: str, limit: int = 10,
                      candidate_id: str | None = None) -> int:
    """Собрать пакеты для needs_package-заявок. Возвращает число собранных. Per-item commit.

    Disclosed answers = глобальные ⊕ per-application (per-app перекрывает по полю).
    Заявки очереди needs_package могут принадлежать разным кандидатам — answer-vault
    скоуплен per-candidate_id, поэтому глобальные answers грузятся пер-заявочно по её
    candidate_id (с кешем на неизменные повторы одного кандидата в пределах раунда).

    candidate_id — скоуп очереди этим кандидатом (иначе глобальный FIFO по всем)."""
    rows = store.pull_needs_package(conn, limit, candidate_id)
    answers_by_candidate: dict[str, list] = {}
    built = 0
    for r in rows:
        if not r["destination_url"]:
            continue  # нет URL подачи — пропустить раундом
        inp = PackageInput(
            application_id=r["application_id"], company=r["company"], role=r["role"],
            destination_url=r["destination_url"], ats_family=r.get("ats_family"),
            fit_summary=r.get("fit_summary", ""),
            hard_requirements=r.get("hard_requirements", []),
            material_unknowns=r.get("material_unknowns", []),
            overclaim_risks=r.get("overclaim_risks", []))
        candidate_id = r["candidate_id"]
        if candidate_id not in answers_by_candidate:
            answers_by_candidate[candidate_id] = store.load_answers(conn, candidate_id)
        answers = answers_by_candidate[candidate_id]
        app_answers = store.load_application_answers(conn, r["application_id"])
        merged = merge_answers(answers, app_answers)
        # answers_version провенансится от merged (global ⊕ per-app), а не только
        # глобального — иначе изменение per-app ответа меняет payload_hash, но не
        # answers_version, и аудит-след расходится (code-review §6).
        answers_version = provenance.answers_version(merged)
        resume = artifacts.select_resume(conn, r["application_id"])
        manifest = build_package(inp, merged, resume)
        descs = artifacts.write_artifacts(base_dir, manifest, render_summary(manifest))
        store.record_package(conn, manifest, descs, answers_version=answers_version)
        conn.commit()
        built += 1
    return built
