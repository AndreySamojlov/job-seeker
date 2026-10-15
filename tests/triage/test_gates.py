from job_machine.triage.gates import CandidateProfile, families_of, role_family_skip
from job_machine.triage.gates_config import load_gate_config

CFG = load_gate_config()
QA_PROFILE = CandidateProfile(roles=["QA", "Head of QA", "Test automation",
                                     "Engineering Manager", "Delivery Manager"],
                              locations=["Europe"], seniority_band="head",
                              company_daily_cap=5)


def test_pm_role_family_skipped():
    # product ∉ семейств кандидата → skip
    assert role_family_skip("(Junior) Product Manager", QA_PROFILE, CFG) == "role_family"
    assert role_family_skip("Product Owner", QA_PROFILE, CFG) == "role_family"


def test_qa_role_passes():
    assert role_family_skip("Senior QA Engineer", QA_PROFILE, CFG) is None
    assert role_family_skip("Head of Quality Engineering", QA_PROFILE, CFG) is None


def test_em_delivery_pass():
    assert role_family_skip("Engineering Manager", QA_PROFILE, CFG) is None
    assert role_family_skip("Delivery Lead", QA_PROFILE, CFG) is None


def test_unknown_family_not_skipped():
    # Ни в одно семейство — отдаём слабому фильтру/LLM, не режем
    assert role_family_skip("Ninja Rockstar Guru", QA_PROFILE, CFG) is None


def test_none_title_not_skipped():
    assert role_family_skip(None, QA_PROFILE, CFG) is None


def test_support_family_skipped():
    assert role_family_skip("Team Lead, Customer Support", QA_PROFILE, CFG) == "role_family"


def test_families_word_boundary_no_spurious_match():
    # ревью-правка: 'qa' не должно ловиться внутри 'Qatar', 'sales' — внутри 'Wholesales'
    assert "qa" not in families_of("Qatar Business Development", CFG)
    assert families_of("Qatar Business Development", CFG) == {"sales"}  # business development
    assert "sales" not in families_of("Wholesales Operations Lead", CFG)
    # позитив сохранён: реальные роли по границам слов распознаются
    assert "qa" in families_of("Senior QA Engineer", CFG)
    assert "product" in families_of("Product Manager, Growth", CFG)


def test_generic_leadership_family_catches_bare_team_leader():
    assert "generic_leadership" in families_of("Engineering Team Leader", CFG)
    assert "generic_leadership" in families_of("Team Lead", CFG)


def test_generic_leadership_does_not_steal_delivery_lead():
    # "delivery lead" остаётся в семье delivery, не переезжает в generic_leadership.
    assert families_of("Delivery Lead", CFG) == {"delivery"}


# --- Task 4: level_band_skip (асимметрия up/down) ---
from job_machine.triage.gates import band_of, level_band_skip  # noqa: E402


def test_band_of():
    assert band_of("Junior QA Engineer", CFG) == "junior"
    assert band_of("VP of Engineering", CFG) == "vp"
    assert band_of("Head of QA", CFG) == "head"
    assert band_of("QA Engineer", CFG) is None   # нет маркера уровня


def test_up_strict():
    # head(5): VP(7) выше на 2 > up_tol(1) → skip
    assert level_band_skip("VP of Quality", QA_PROFILE, CFG) == "level_band"


def test_up_one_stretch_allowed():
    # director(6) выше на 1 == up_tol(1) → НЕ skip
    assert level_band_skip("Director of QA", QA_PROFILE, CFG) is None


def test_down_lenient():
    # senior(3) ниже на 2 <= down_tol(3) → НЕ skip
    assert level_band_skip("Senior QA Engineer", QA_PROFILE, CFG) is None


def test_down_extreme_skipped():
    # junior(1) ниже на 4 > down_tol(3) → skip
    assert level_band_skip("Junior QA", QA_PROFILE, CFG) == "level_band"


def test_unknown_band_not_skipped():
    assert level_band_skip("QA Engineer", QA_PROFILE, CFG) is None


def test_null_candidate_band_disables_gate():
    p = CandidateProfile(roles=["QA"], locations=["Europe"],
                         seniority_band=None, company_daily_cap=5)
    assert level_band_skip("Junior QA", p, CFG) is None


# --- Task 5: geo_skip ---
from job_machine.triage.gates import geo_skip  # noqa: E402


def test_europe_passes():
    assert geo_skip("Berlin, Germany", QA_PROFILE, CFG) is None
    assert geo_skip("Remote - EU", QA_PROFILE, CFG) is None


def test_unknown_passes():
    assert geo_skip("Somewhere", QA_PROFILE, CFG) is None
    assert geo_skip(None, QA_PROFILE, CFG) is None


def test_non_europe_skipped():
    assert geo_skip("San Francisco, CA", QA_PROFILE, CFG) == "geo_ineligible"
    assert geo_skip("Bangalore, India", QA_PROFILE, CFG) == "geo_ineligible"


def test_global_remote_exception():
    assert geo_skip("Remote - Global", QA_PROFILE, CFG) is None
    assert geo_skip("Worldwide", QA_PROFILE, CFG) is None


# --- Task 6: dedup_skip + fit_proxy ---
from job_machine.triage.gates import (  # noqa: E402
    GateRow, PassState, dedup_skip, fit_proxy, normalize_title)


def _row(vid="v1", url="https://boards.greenhouse.io/acme/jobs/123",
         ats="greenhouse", company="Acme", title="QA Engineer",
         location="Berlin", work_mode="remote", has_dup_event=False):
    return GateRow(vacancy_id=vid, source_url=url, ats_family=ats, company=company,
                   title=title, location=location, work_mode=work_mode,
                   has_requisition_dup_event=has_dup_event)


def test_dedup_by_post_identity_in_pass():
    st = PassState()
    a = _row(vid="v1", url="https://boards.greenhouse.io/acme/jobs/123")
    b = _row(vid="v2", url="https://job-boards.eu.greenhouse.io/acme/jobs/123?loc=x")
    assert dedup_skip(a, st, CFG) is None       # первый — записывает
    assert dedup_skip(b, st, CFG) == "requisition_duplicate"  # тот же пост


def test_dedup_by_company_title():
    st = PassState()
    a = _row(vid="v1", url="https://x.com/1", ats="lever", company="Remote", title="Data Engineer (ETL)")
    b = _row(vid="v2", url="https://x.com/2", ats="lever", company="remote", title="data engineer  (etl)")
    assert dedup_skip(a, st, CFG) is None
    assert dedup_skip(b, st, CFG) == "requisition_duplicate"


def test_dedup_seeds_from_prior():
    st = PassState(seen_posts={"gh:acme:123"})
    assert dedup_skip(_row(url="https://boards.greenhouse.io/acme/jobs/123"), st, CFG) == "requisition_duplicate"


def test_dedup_fill_worker_event():
    st = PassState()
    assert dedup_skip(_row(has_dup_event=True), st, CFG) == "requisition_duplicate"


def test_fit_proxy_orders_by_relevance():
    hi = fit_proxy(_row(title="Head of QA", location="Berlin"), QA_PROFILE, CFG)
    lo = fit_proxy(_row(title="Data Engineer", location="San Francisco"), QA_PROFILE, CFG)
    assert hi > lo


def test_normalize_title():
    assert normalize_title("Data Engineer  (ETL)") == normalize_title("data engineer (etl)")


# --- Task 7: apply_company_cap (батч) ---
from job_machine.triage.gates import apply_company_cap  # noqa: E402


def test_cap_keeps_top_fit():
    st = PassState(company_counts_today={})
    cfg2 = load_gate_config()   # cap default 5; используем cap=2 через профиль
    prof = CandidateProfile(roles=["QA"], locations=["Europe"],
                            seniority_band="head", company_daily_cap=2)
    rows = [_row(vid=f"v{i}", company="Flood",
                 title=t, location="Berlin")
            for i, t in enumerate(["Head of QA", "Senior QA", "QA Engineer",
                                   "Junior QA", "QA Analyst"])]
    kept, capped = apply_company_cap(rows, st, prof, cfg2)
    assert len(kept) == 2
    assert {r.vacancy_id for r in kept} == {"v0", "v1"}   # топ-2 по фиту
    assert len(capped) == 3
    assert all(reason == "company_daily_cap" for _, reason in capped)


def test_cap_respects_today_count():
    st = PassState(company_counts_today={"flood": 2})
    prof = CandidateProfile(roles=["QA"], locations=["Europe"],
                            seniority_band="head", company_daily_cap=2)
    rows = [_row(vid="v1", company="Flood", title="Head of QA")]
    kept, capped = apply_company_cap(rows, st, prof, load_gate_config())
    assert kept == []
    assert len(capped) == 1


def test_cap_default_when_null():
    st = PassState()
    prof = CandidateProfile(roles=["QA"], locations=["Europe"],
                            seniority_band="head", company_daily_cap=None)
    rows = [_row(vid=f"v{i}", company="X", title="QA Engineer") for i in range(6)]
    kept, capped = apply_company_cap(rows, st, prof, load_gate_config())
    assert len(kept) == 5    # дефолт 5
    assert len(capped) == 1
