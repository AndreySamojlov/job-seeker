import pytest
from psycopg.types.json import Json

from job_machine.db import migrate
from job_machine.triage import store
from job_machine.triage.models import TriageVerdict


def _apply(conn):
    for m in migrate.pending(migrate.discover_migrations("db/migrations"),
                             migrate.applied_migrations(conn)):
        migrate.apply_migration(conn, m)


def _seed_vacancy(conn, title, location, work_mode="remote"):
    with conn.cursor() as cur:
        cur.execute(
            "insert into vacancy (canonical_url, source_url, company, title, location, "
            "work_mode, vacancy_status, state) values "
            "('https://x/1','https://x/1','Acme',%s,%s,%s,'verified','verified') "
            "returning vacancy_id", (title, location, work_mode))
        vid = cur.fetchone()[0]
    conn.commit()
    return vid


def _seed_candidate(conn, candidate_id, languages, hands_on_band="light"):
    with conn.cursor() as cur:
        cur.execute("insert into candidate (candidate_id, name) values (%s,%s) "
                    "on conflict do nothing", (candidate_id, candidate_id))
        cur.execute(
            "insert into search_profile (candidate_id, roles, locations, languages, "
            "seniority_band, hands_on_band, domains) values (%s,%s,%s,%s,%s,%s,%s)",
            (candidate_id, Json(["QA Lead"]), Json(["Europe"]), Json(languages),
             "lead", hands_on_band, Json(["gaming"])))
    conn.commit()


def _insert_vacancy(conn, company="Acme", title="QA Engineer",
                    url="https://boards.greenhouse.io/acme/jobs/1",
                    ats="greenhouse", location="Berlin", work_mode="remote"):
    with conn.cursor() as cur:
        cur.execute(
            "insert into vacancy (source_url, canonical_url, company, title, "
            "location, work_mode, ats_family, vacancy_status) "
            "values (%s,%s,%s,%s,%s,%s,%s,'verified') returning vacancy_id",
            (url, url, company, title, location, work_mode, ats))
        return cur.fetchone()[0]


@pytest.mark.db
def test_load_candidate_profile(db_schema):
    conn, _ = db_schema
    _apply(conn)
    prof = store.load_candidate_profile(conn, "andrey-s")
    assert prof.seniority_band == "head"
    assert prof.company_daily_cap == 5
    assert prof.locations
    assert prof.roles


@pytest.mark.db
def test_load_candidate_profile_missing(db_schema):
    conn, _ = db_schema
    _apply(conn)
    prof = store.load_candidate_profile(conn, "no-such-candidate")
    assert prof.roles == []
    assert prof.locations == []
    assert prof.seniority_band is None
    assert prof.company_daily_cap is None


@pytest.mark.db
def test_company_counts_today_from_applications(db_schema):
    conn, _ = db_schema
    _apply(conn)
    vid = _insert_vacancy(conn, company="Doctolib", title="EM")
    with conn.cursor() as cur:
        cur.execute("insert into application (vacancy_id, candidate_id, state) "
                    "values (%s,'andrey-s','needs_package')", (vid,))
    conn.commit()
    counts = store.load_company_counts_today(conn, "andrey-s")
    assert isinstance(counts, dict)
    assert counts.get("doctolib") == 1


@pytest.mark.db
def test_seen_requisitions_from_triaged(db_schema):
    conn, _ = db_schema
    _apply(conn)
    vid = _insert_vacancy(conn, company="Acme", title="QA Engineer",
                          url="https://boards.greenhouse.io/acme/jobs/42")
    with conn.cursor() as cur:
        cur.execute("insert into triage_result (candidate_id, vacancy_id, verdict) "
                    "values ('andrey-s',%s,'skip')", (vid,))
    conn.commit()
    posts, cts = store.load_seen_requisitions(conn, "andrey-s")
    assert "gh:acme:42" in posts
    assert ("acme", "qa engineer") in cts


@pytest.mark.db
def test_record_quick_skip_new_reasons(db_schema):
    conn, _ = db_schema
    _apply(conn)
    vid = _insert_vacancy(conn)
    store.record_quick_skip(conn, "andrey-s", vid, "geo_ineligible", {"location": "SF"})
    conn.commit()
    with conn.cursor() as cur:
        cur.execute("select verdict from triage_result where candidate_id='andrey-s' "
                    "and vacancy_id=%s", (vid,))
        assert cur.fetchone()[0] == "skip"
        cur.execute("select payload_json->>'reason' from event "
                    "where entity_id=%s and event_type='vacancy.quick_skipped'", (vid,))
        assert cur.fetchone()[0] == "geo_ineligible"


@pytest.mark.db
def test_apply_verdict_forces_skip_below_fit_floor(db_schema):
    from job_machine.triage.models import HardRequirementMatch, TriageVerdict
    from job_machine.triage import store

    conn, _ = db_schema
    _apply(conn)
    vid = _insert_vacancy(conn, company="Remote", title="Engineering Team Leader",
                          location="Remote-Nordics", work_mode="remote")
    # 3 gap → requirements=0; "Engineering Team Leader" не матчит семью кандидата (role=0);
    # geo Nordics вне Europe/allowed → пусть classify_location даст non-europe → composite
    # заведомо ниже 40 (band D).
    v = TriageVerdict(
        vacancy_id=str(vid), verdict="apply", fit_summary="x",
        hard_requirements=[HardRequirementMatch(requirement=f"r{i}", status="gap")
                           for i in range(3)],
        material_unknowns=[], overclaim_risks=[])
    route = store.apply_verdict(conn, v, "andrey-s")
    conn.commit()
    assert route == "skipped"
    with conn.cursor() as cur:
        cur.execute("select verdict, fit_band from triage_result "
                    "where candidate_id='andrey-s' and vacancy_id=%s", (vid,))
        row = cur.fetchone()
        assert row[0] == "skip"
        assert row[1] == "D"
        cur.execute("select payload_json->>'skip_reason' from event "
                    "where entity_id=%s and event_type='vacancy.skipped'", (vid,))
        assert cur.fetchone()[0] == "fit_floor"


@pytest.mark.db
def test_apply_verdict_respects_llm_verdict_above_fit_floor(db_schema):
    from job_machine.triage.models import HardRequirementMatch, TriageVerdict
    from job_machine.triage import store

    conn, _ = db_schema
    _apply(conn)
    vid = _insert_vacancy(conn, company="Acme", title="QA Engineer",
                          location="Berlin, Germany", work_mode="remote")
    v = TriageVerdict(
        vacancy_id=str(vid), verdict="apply", fit_summary="x",
        hard_requirements=[HardRequirementMatch(requirement="r0", status="strong")],
        material_unknowns=[], overclaim_risks=[])
    route = store.apply_verdict(conn, v, "andrey-s")
    conn.commit()
    assert route == "needs_package"
    with conn.cursor() as cur:
        cur.execute("select verdict from triage_result "
                    "where candidate_id='andrey-s' and vacancy_id=%s", (vid,))
        assert cur.fetchone()[0] == "apply"


@pytest.mark.db
def test_eligibility_block_skips_without_score(migrated):
    conn, _ = migrated
    vid = _seed_vacancy(conn, title="QA Lead", location="Munich, Germany")
    _seed_candidate(conn, "c1", languages=["English"])
    v = TriageVerdict(
        vacancy_id=str(vid), verdict="apply", fit_summary="x", hard_requirements=[],
        eligibility={"required_languages": [{"language": "German", "level": "C1",
                                             "mandatory": True}]})
    route = store.apply_verdict(conn, v, "c1")
    assert route == "skipped"
    with conn.cursor() as cur:
        cur.execute("select verdict, fit_score, fit_band, eligibility, material_unknowns "
                    "from triage_result where candidate_id='c1' and vacancy_id=%s", (vid,))
        verdict, score, band, elig, unknowns = cur.fetchone()
    assert verdict == "skip"
    # Скор пригодности не считается: блокировка допуска — не «плохой фит».
    assert score is None and band is None
    assert elig["blocked"] is True and elig["category"] == "mandatory_language"


@pytest.mark.db
def test_disclosed_unknown_reaches_material_unknowns(migrated):
    conn, _ = migrated
    vid = _seed_vacancy(conn, title="QA Lead", location="Berlin, Germany")
    _seed_candidate(conn, "c1", languages=["English"])
    v = TriageVerdict(
        vacancy_id=str(vid), verdict="apply", fit_summary="x",
        hard_requirements=[{"requirement": "QA", "status": "strong"}],
        eligibility={"work_authorization": {"requires_local_right": True}})
    store.apply_verdict(conn, v, "c1")
    with conn.cursor() as cur:
        cur.execute("select verdict, material_unknowns from triage_result "
                    "where candidate_id='c1' and vacancy_id=%s", (vid,))
        verdict, unknowns = cur.fetchone()
    assert verdict != "skip"
    assert any("sponsorship" in u.lower() for u in unknowns)


@pytest.mark.db
def test_capped_by_persisted(migrated):
    conn, _ = migrated
    vid = _seed_vacancy(conn, title="QA Lead", location="Berlin, Germany")
    _seed_candidate(conn, "c1", languages=["English"], hands_on_band="none")
    v = TriageVerdict(
        vacancy_id=str(vid), verdict="apply", fit_summary="x",
        hard_requirements=[{"requirement": "QA", "status": "strong"}],
        hands_on={"required_level": "deep"})
    store.apply_verdict(conn, v, "c1")
    with conn.cursor() as cur:
        cur.execute("select capped_by from triage_result "
                    "where candidate_id='c1' and vacancy_id=%s", (vid,))
        (capped,) = cur.fetchone()
    assert "hands_on" in capped


@pytest.mark.db
def test_fit_floor_does_not_fire_on_unparsed_requirements(migrated):
    """Авторизация владельца 2026-08-15: гейт band D применяется только к РАЗОБРАННЫМ
    вакансиям. Без разбора композит физически не может превысить 24.5 балла, поэтому
    безусловный гейт гасил бы «непонятые» вакансии, а не «плохие»."""
    conn, _ = migrated
    _seed_candidate(conn, "c1", ["English"])
    vid = _seed_vacancy(conn, title="QA Lead", location="Berlin, Germany")
    conn.commit()
    v = TriageVerdict(vacancy_id=str(vid), verdict="apply",
                      fit_summary="facts could not be extracted",
                      hard_requirements=[])
    route = store.apply_verdict(conn, v, "c1")
    conn.commit()
    assert route == "needs_package"
    with conn.cursor() as cur:
        cur.execute("select verdict, fit_band, fit_breakdown->'flags' from triage_result "
                    "where candidate_id='c1' and vacancy_id=%s", (vid,))
        verdict, band, flags = cur.fetchone()
    assert verdict == "apply" and band == "D"
    assert "requirements_not_parsed" in flags


@pytest.mark.db
def test_fit_floor_still_fires_on_parsed_poor_fit(migrated):
    """Обратная сторона: разобранная и объективно слабая вакансия по-прежнему гасится."""
    conn, _ = migrated
    _seed_candidate(conn, "c1", ["English"])
    vid = _seed_vacancy(conn, title="Chef de Cuisine", location="Austin, Texas")
    conn.commit()
    v = TriageVerdict(vacancy_id=str(vid), verdict="apply", fit_summary="weak",
                      hard_requirements=[{"requirement": "sous-vide", "status": "gap"}])
    route = store.apply_verdict(conn, v, "c1")
    conn.commit()
    assert route == "skipped"
    with conn.cursor() as cur:
        cur.execute("select verdict, fit_band from triage_result "
                    "where candidate_id='c1' and vacancy_id=%s", (vid,))
        assert cur.fetchone() == ("skip", "D")
