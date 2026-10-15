import json

import pytest

from job_machine import audit
from job_machine.db import migrate
from job_machine.discovery import store as dstore
from job_machine.discovery.models import VacancyRecord
from job_machine.triage import store as tstore

import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "requeue_quick_skips",
    Path(__file__).resolve().parents[2] / "scripts" / "requeue_quick_skips.py")
requeue = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(requeue)


def _apply_migrations(conn):
    for m in migrate.pending(migrate.discover_migrations("db/migrations"),
                             migrate.applied_migrations(conn)):
        migrate.apply_migration(conn, m)


def _mk_vacancy(conn, canonical, title, work_mode="onsite"):
    rec = VacancyRecord(
        source="greenhouse",
        source_url=f"https://boards-api.greenhouse.io/v1/boards/acme/jobs/{canonical[-1]}",
        canonical_url=canonical, company="Acme", normalized_company="acme",
        title=title, normalized_title=title.lower(), location="Berlin, Germany",
        work_mode=work_mode, ats_family="greenhouse",
    )
    vid = dstore.upsert_vacancy(conn, rec)
    dstore.mark_verified(conn, vid)
    return vid


def _set_andrey_roles(conn, roles):
    """andrey-s уже сидируется миграцией 0010 (roles=["QA","Test automation"]) —
    UPDATE вместо INSERT, чтобы не конфликтовать с PK search_profile."""
    with conn.cursor() as cur:
        cur.execute(
            "insert into search_profile (candidate_id, roles) values (%s, %s::jsonb) "
            "on conflict (candidate_id) do update set roles=excluded.roles",
            ("andrey-s", json.dumps(roles)))


@pytest.mark.db
def test_requeue_rescues_prefilter_skips_only(db_schema):
    conn, _ = db_schema
    _apply_migrations(conn)
    _set_andrey_roles(conn, ["Engineering Team Leader", "QA Lead"])

    # целевая, отсечённая старым work_mode-префильтром — спасаем
    vid_rescue = _mk_vacancy(conn, "https://boards.greenhouse.io/acme/jobs/1",
                             "Engineering Team Leader")
    tstore.record_quick_skip(conn, "andrey-s", vid_rescue, "work_mode",
                             {"title": "Engineering Team Leader"})
    # нецелевой тайтл — не спасаем
    vid_notarget = _mk_vacancy(conn, "https://boards.greenhouse.io/acme/jobs/2",
                               "Office Manager")
    tstore.record_quick_skip(conn, "andrey-s", vid_notarget, "title_mismatch",
                             {"title": "Office Manager"})
    # LLM-скип (тайтл проходит роль-фильтр, но есть vacancy.skipped для этого
    # кандидата — квик-скип уже не единственный источник skip) — не трогаем
    vid_llm = _mk_vacancy(conn, "https://boards.greenhouse.io/acme/jobs/3",
                          "QA Lead")
    tstore.record_quick_skip(conn, "andrey-s", vid_llm, "work_mode", {"title": "QA Lead"})
    audit.emit_event(conn, "vacancy", vid_llm, "vacancy.skipped",
                     {"verdict": "skip", "candidate_id": "andrey-s"})
    conn.commit()

    rescued = requeue.requeue(conn, dry_run=False)
    assert set(rescued) == {vid_rescue}

    with conn.cursor() as cur:
        # общий vacancy.state/vacancy_status НЕ трогается — квик-скип и его откат
        # живут в per-candidate triage_result-леджере, не в общей вакансии.
        cur.execute("select vacancy_status, state from vacancy where vacancy_id=%s",
                    (vid_rescue,))
        assert cur.fetchone() == ("verified", "verified")
        cur.execute("select count(*) from event where event_type='vacancy.requeued'")
        assert cur.fetchone()[0] == 1
        # спасённая вакансия: строка в triage_result для andrey-s удалена —
        # снова попадёт в pull_untriaged_for_candidate.
        cur.execute("select count(*) from triage_result "
                    "where candidate_id='andrey-s' and vacancy_id=%s", (vid_rescue,))
        assert cur.fetchone()[0] == 0
        # нецелевая и LLM-скип — их triage_result-строки остаются нетронутыми
        cur.execute("select verdict from triage_result "
                    "where candidate_id='andrey-s' and vacancy_id=%s", (vid_notarget,))
        assert cur.fetchone()[0] == "skip"
        cur.execute("select verdict from triage_result "
                    "where candidate_id='andrey-s' and vacancy_id=%s", (vid_llm,))
        assert cur.fetchone()[0] == "skip"


@pytest.mark.db
def test_requeue_delete_guard_preserves_concurrent_llm_verdict(db_schema):
    """Гонка: между SELECT и DELETE параллельный LLM-триаж мог переписать
    verdict квик-скипа (например, на 'apply'). DELETE guard'ится verdict='skip'
    в WHERE — не должен снести уже принятое LLM-решение (наихудший случай гонки:
    потеря 'apply'). Симулируем гонку напрямую: сначала record_quick_skip
    (verdict='skip'), затем — как будто конкурентный apply_verdict успел
    отработать первым — вручную переводим verdict на 'apply', и только затем
    прогоняем DELETE-запрос скрипта."""
    conn, _ = db_schema
    _apply_migrations(conn)
    vid = _mk_vacancy(conn, "https://boards.greenhouse.io/acme/jobs/1",
                      "Engineering Team Leader")
    tstore.record_quick_skip(conn, "andrey-s", vid, "work_mode", {})
    conn.commit()

    # конкурентный LLM-триаж «выиграл гонку» и успел проставить apply раньше DELETE
    with conn.cursor() as cur:
        cur.execute(
            "update triage_result set verdict='apply' "
            "where candidate_id='andrey-s' and vacancy_id=%s", (vid,))
    conn.commit()

    with conn.cursor() as cur:
        cur.execute(requeue._DELETE_TRIAGE_RESULT, ("andrey-s", vid))
        deleted = cur.rowcount
    conn.commit()

    assert deleted == 0  # guard не дал снести чужой (не 'skip') вердикт
    with conn.cursor() as cur:
        cur.execute("select verdict from triage_result "
                    "where candidate_id='andrey-s' and vacancy_id=%s", (vid,))
        assert cur.fetchone()[0] == "apply"  # LLM-решение цело


@pytest.mark.db
def test_requeue_dry_run_changes_nothing(db_schema):
    conn, _ = db_schema
    _apply_migrations(conn)
    _set_andrey_roles(conn, ["Engineering Team Leader"])
    vid = _mk_vacancy(conn, "https://boards.greenhouse.io/acme/jobs/1",
                      "Engineering Team Leader")
    tstore.record_quick_skip(conn, "andrey-s", vid, "work_mode", {})
    conn.commit()

    rescued = requeue.requeue(conn, dry_run=True)
    assert set(rescued) == {vid}
    with conn.cursor() as cur:
        # dry-run: triage_result-строка остаётся на месте, событие не пишется
        cur.execute("select verdict from triage_result "
                    "where candidate_id='andrey-s' and vacancy_id=%s", (vid,))
        assert cur.fetchone()[0] == "skip"
        cur.execute("select count(*) from event where event_type='vacancy.requeued'")
        assert cur.fetchone()[0] == 0
