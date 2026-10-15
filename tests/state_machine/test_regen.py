import pytest
from job_machine.db import migrate
from job_machine.state_machine import regen


def _apply(conn):
    for m in migrate.pending(migrate.discover_migrations("db/migrations"),
                             migrate.applied_migrations(conn)):
        migrate.apply_migration(conn, m)


def _seed(conn, state, with_resume):
    with conn.cursor() as cur:
        cur.execute("insert into vacancy (company,title,canonical_url,state) "
                    "values ('Acme','QA','https://a/1','triaged') returning vacancy_id")
        vid = cur.fetchone()[0]
        cur.execute("insert into application (vacancy_id,candidate_id,state,current_blocker) "
                    "values (%s,'andrey-s',%s,'ambiguous') returning application_id", (vid, state))
        aid = cur.fetchone()[0]
        if with_resume:
            cur.execute("insert into artifact (application_id,artifact_type,path_or_uri,content_hash) "
                        "values (%s,'resume','/r.pdf','h') returning artifact_id", (aid,))
            rid = cur.fetchone()[0]
            cur.execute("update application set resume_artifact_id=%s where application_id=%s",
                        (rid, aid))
    return str(aid)


@pytest.mark.db
def test_reopen_fill_blocked_resets_for_regen(db_schema):
    conn, _ = db_schema
    _apply(conn)
    aid = _seed(conn, "fill_blocked", with_resume=True)
    conn.commit()
    res = regen.reopen_for_regen(conn, aid)
    assert res["ok"] is True
    with conn.cursor() as cur:
        cur.execute("select state, current_blocker, resume_artifact_id "
                    "from application where application_id=%s", (aid,))
        state, blocker, rid = cur.fetchone()
        cur.execute("select count(*) from event where entity_id=%s "
                    "and event_type='application.reopened'", (aid,))
        events = cur.fetchone()[0]
    assert state == "needs_package"
    assert blocker is None
    assert rid is None
    assert events == 1


@pytest.mark.db
def test_reopen_submit_blocked_resets_for_regen(db_schema):
    """task_e70e18b1: submit_blocked (e.g. a stale job-browser deploy causing a
    false mandatory_unknown, see docs/superpowers/specs — job-browser group_label
    regression 2026-07-19) must be reopenable the same way fill_blocked already is —
    reset resume/blocker and send the application back through needs_package so
    repackage/fill/approval/submit all re-run against the fixed pipeline."""
    conn, _ = db_schema
    _apply(conn)
    aid = _seed(conn, "submit_blocked", with_resume=True)
    conn.commit()
    res = regen.reopen_for_regen(conn, aid)
    assert res["ok"] is True
    with conn.cursor() as cur:
        cur.execute("select state, current_blocker, resume_artifact_id "
                    "from application where application_id=%s", (aid,))
        state, blocker, rid = cur.fetchone()
        cur.execute("select count(*) from event where entity_id=%s "
                    "and event_type='application.reopened'", (aid,))
        events = cur.fetchone()[0]
    assert state == "needs_package"
    assert blocker is None
    assert rid is None
    assert events == 1


@pytest.mark.db
def test_reopen_rejects_active_handoff(db_schema):
    """Активный ручной хендофф (CAPTCHA/MFA) теперь лежит в каноничной паре
    state='fill_blocked' + current_blocker='handoff_manual' (миграция 0021 убрала
    отдельное значение state='handoff_manual'). reopen_for_regen обязан по-прежнему
    отказывать на живом хендоффе тем же manual_fail_and_refile, что и раньше —
    иначе перегенерация резюме тихо сбросит current_blocker/resume_artifact_id и
    осиротит живую браузерную сессию, за которой сидит человек, решающий капчу."""
    conn, _ = db_schema
    _apply(conn)
    with conn.cursor() as cur:
        cur.execute("insert into vacancy (company,title,canonical_url,state) "
                    "values ('Acme','QA','https://a/handoff','triaged') "
                    "returning vacancy_id")
        vid = cur.fetchone()[0]
        cur.execute("insert into application (vacancy_id,candidate_id,state,current_blocker) "
                    "values (%s,'andrey-s','fill_blocked','handoff_manual') "
                    "returning application_id", (vid,))
        aid = str(cur.fetchone()[0])
    conn.commit()
    res = regen.reopen_for_regen(conn, aid)
    assert res["ok"] is False
    assert res["reopen_policy"] == "manual_fail_and_refile"


@pytest.mark.db
def test_reopen_rejects_nonreopenable_state(db_schema):
    conn, _ = db_schema
    _apply(conn)
    aid = _seed(conn, "submitted", with_resume=False)
    conn.commit()
    res = regen.reopen_for_regen(conn, aid)
    assert res["ok"] is False
    assert res["reopen_policy"] == "manual_fail_and_refile"


@pytest.mark.db
def test_reopen_non_reopenable_state_rejected(db_schema):
    conn, _ = db_schema
    _apply(conn)
    aid = _seed(conn, "pre_submit_ready", with_resume=False)
    conn.commit()
    res = regen.reopen_for_regen(conn, aid)
    assert res["ok"] is False
    assert res["reopen_policy"] == "manual_fail_and_refile"


@pytest.mark.db
def test_reopen_needs_package_with_stale_resume_resets_without_transition(db_schema):
    conn, _ = db_schema
    _apply(conn)
    aid = _seed(conn, "needs_package", with_resume=True)
    conn.commit()
    res = regen.reopen_for_regen(conn, aid)
    assert res["ok"] is True
    with conn.cursor() as cur:
        cur.execute("select state, current_blocker, resume_artifact_id "
                    "from application where application_id=%s", (aid,))
        state, blocker, rid = cur.fetchone()
        cur.execute("select count(*) from event where entity_id=%s "
                    "and event_type='application.reopened'", (aid,))
        events = cur.fetchone()[0]
    assert state == "needs_package"
    assert blocker is None
    assert rid is None
    assert events == 1


@pytest.mark.db
def test_refile_marks_old_failed_and_creates_fresh_needs_package(db_schema):
    """pre_submit_ready — каноничное состояние вне _REOPENABLE: реально
    исполненный шаг воронки, откатывать который через reopen нельзя без потери
    прогресса. submit_blocked сюда больше не годится: task_e70e18b1 сделал его
    реопенабельным, теперь это пример для test_reopen_submit_blocked_resets_for_regen.
    Значений вне ApplicationState в БД больше не бывает — их запрещает
    application_state_canonical_chk (миграция 0021)."""
    conn, _ = db_schema
    _apply(conn)
    aid = _seed(conn, "pre_submit_ready", with_resume=True)
    with conn.cursor() as cur:
        cur.execute("update application set verdict='apply_with_caveat', "
                    "claims_version='v3' where application_id=%s", (aid,))
    conn.commit()

    res = regen.refile_application(conn, aid)

    assert res["ok"] is True
    assert res["old_application_id"] == aid
    new_aid = res["new_application_id"]
    assert new_aid != aid
    with conn.cursor() as cur:
        cur.execute("select state, current_blocker from application where application_id=%s",
                    (aid,))
        old_state, old_blocker = cur.fetchone()
        cur.execute("select state, verdict, claims_version, current_blocker, "
                    "resume_artifact_id, vacancy_id, candidate_id "
                    "from application where application_id=%s", (new_aid,))
        new_row = cur.fetchone()
        cur.execute("select count(*) from event where entity_id=%s "
                    "and event_type='application.failed'", (aid,))
        failed_events = cur.fetchone()[0]
        cur.execute("select count(*) from event where entity_id=%s "
                    "and event_type='application.refiled'", (new_aid,))
        refiled_events = cur.fetchone()[0]
    assert old_state == "failed"
    # Старый current_blocker остаётся нетронутым — история диагностики не стирается.
    assert old_blocker == "ambiguous"
    assert new_row[0] == "needs_package"
    assert new_row[1] == "apply_with_caveat"
    assert new_row[2] == "v3"
    assert new_row[3] is None
    assert new_row[4] is None
    assert failed_events == 1
    assert refiled_events == 1


@pytest.mark.db
def test_refile_active_handoff_marks_failed_and_creates_fresh_needs_package(db_schema):
    """Заявка с активным ручным хендоффом (state='fill_blocked' +
    current_blocker='handoff_manual') — reopen_for_regen на ней сознательно
    отказывает (test_reopen_rejects_active_handoff), значит refile_application
    обязан быть для неё проходным путём восстановления, иначе получается тупик:
    reopen говорит "иди в refile", refile говорит "иди в reopen", и заявка не
    восстановима вообще никак через API (регрессия, найденная code review
    2026-08-05, вторая половина после guard в reopen_for_regen)."""
    conn, _ = db_schema
    _apply(conn)
    with conn.cursor() as cur:
        cur.execute("insert into vacancy (company,title,canonical_url,state) "
                    "values ('Acme','QA','https://a/handoff-refile','triaged') "
                    "returning vacancy_id")
        vid = cur.fetchone()[0]
        cur.execute("insert into application (vacancy_id,candidate_id,state,current_blocker) "
                    "values (%s,'andrey-s','fill_blocked','handoff_manual') "
                    "returning application_id", (vid,))
        aid = str(cur.fetchone()[0])
        cur.execute("update application set verdict='apply_with_caveat', "
                    "claims_version='v3' where application_id=%s", (aid,))
    conn.commit()

    res = regen.refile_application(conn, aid)

    assert res["ok"] is True
    assert res["old_application_id"] == aid
    new_aid = res["new_application_id"]
    assert new_aid != aid
    with conn.cursor() as cur:
        cur.execute("select state, current_blocker from application where application_id=%s",
                    (aid,))
        old_state, old_blocker = cur.fetchone()
        cur.execute("select state, verdict, claims_version, current_blocker, resume_artifact_id "
                    "from application where application_id=%s", (new_aid,))
        new_row = cur.fetchone()
        cur.execute("select count(*) from event where entity_id=%s "
                    "and event_type='application.failed'", (aid,))
        failed_events = cur.fetchone()[0]
        cur.execute("select count(*) from event where entity_id=%s "
                    "and event_type='application.refiled'", (new_aid,))
        refiled_events = cur.fetchone()[0]
    assert old_state == "failed"
    # Старый current_blocker остаётся нетронутым — история диагностики не стирается.
    assert old_blocker == "handoff_manual"
    assert new_row[0] == "needs_package"
    assert new_row[1] == "apply_with_caveat"
    assert new_row[2] == "v3"
    assert new_row[3] is None
    assert new_row[4] is None
    assert failed_events == 1
    assert refiled_events == 1


@pytest.mark.db
def test_refile_rejects_reopenable_state(db_schema):
    conn, _ = db_schema
    _apply(conn)
    aid = _seed(conn, "fill_blocked", with_resume=True)
    conn.commit()
    res = regen.refile_application(conn, aid)
    assert res["ok"] is False
    assert "reopen_for_regen" in res["error"]


@pytest.mark.db
def test_refile_rejects_when_active_application_already_exists_for_vacancy(db_schema):
    conn, _ = db_schema
    _apply(conn)
    aid = _seed(conn, "pre_submit_ready", with_resume=False)
    with conn.cursor() as cur:
        cur.execute("select vacancy_id from application where application_id=%s", (aid,))
        vid = cur.fetchone()[0]
        cur.execute("insert into application (vacancy_id,candidate_id,state) "
                    "values (%s,'andrey-s','needs_package') returning application_id", (vid,))
        other_aid = cur.fetchone()[0]
    conn.commit()

    res = regen.refile_application(conn, aid)

    assert res["ok"] is False
    assert res["existing_application_id"] == str(other_aid)


@pytest.mark.db
def test_reopen_needs_package_without_resume_is_noop(db_schema):
    conn, _ = db_schema
    _apply(conn)
    aid = _seed(conn, "needs_package", with_resume=False)
    conn.commit()
    res = regen.reopen_for_regen(conn, aid)
    assert res["ok"] is True
    assert res.get("no_op") is True
    # current_blocker (e.g. triage_skip — a deliberate "don't package" marker set by
    # triage/store.py apply_verdict on an apply->skip flip) must survive untouched: a
    # resume-regen no-op must not silently re-admit a triage-skipped application into
    # run_package's queue. Surfaced in the response so callers don't read no_op as "fully
    # healthy" when it may still be excluded for an unrelated reason.
    assert res["current_blocker"] == "ambiguous"
    with conn.cursor() as cur:
        cur.execute("select current_blocker from application where application_id=%s", (aid,))
        blocker = cur.fetchone()[0]
        cur.execute("select count(*) from event where entity_id=%s "
                    "and event_type='application.reopened'", (aid,))
        events = cur.fetchone()[0]
    assert blocker == "ambiguous"
    assert events == 0
