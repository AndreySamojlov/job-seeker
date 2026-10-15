from job_machine.discovery.models import (
    RawArbeitnowJob, RawAshbyJob, RawDjinniJob, RawGreenhouseJob, RawHimalayasJob,
    RawJobicyJob, RawKarieraJob, RawLandingJobsJob, RawLeverJob, RawNetEmpregosJob,
    RawPinpointJob, RawRecruiteeJob, RawRemotiveJob, RawSmartRecruitersJob, RawWorkableJob,
    RawWwrJob,
)
from job_machine.discovery.normalize import (
    api_job_url, arbeitnow_to_record, ashby_to_record, canonicalize_url, djinni_to_record,
    himalayas_to_record, infer_work_mode, infer_work_mode_from_flags, jobicy_to_record,
    kariera_to_record, landing_jobs_to_record, lever_to_record, net_empregos_to_record,
    normalize_text, pinpoint_to_record, recruitee_to_record, remotive_to_record,
    smartrecruiters_to_record, to_vacancy_record, workable_to_record, wwr_to_record,
)


def test_canonicalize_strips_query_case_and_trailing_slash():
    assert canonicalize_url("HTTPS://Boards.Greenhouse.io/acme/jobs/42/?gh_src=abc") == \
        "https://boards.greenhouse.io/acme/jobs/42"


def test_canonicalize_keeps_clean_url():
    assert canonicalize_url("https://boards.greenhouse.io/acme/jobs/1") == \
        "https://boards.greenhouse.io/acme/jobs/1"


def test_normalize_text_collapses_ws_and_casefolds():
    assert normalize_text("  Senior   Backend  Engineer ") == "senior backend engineer"
    assert normalize_text(None) is None
    assert normalize_text("   ") is None


def test_infer_work_mode():
    assert infer_work_mode("Remote - EU") == "remote"
    assert infer_work_mode("Hybrid (Berlin)") == "hybrid"
    assert infer_work_mode("Berlin, Germany") == "onsite"
    assert infer_work_mode("") == "unknown"
    assert infer_work_mode(None) == "unknown"


def test_api_job_url():
    assert api_job_url("acme", 42) == \
        "https://boards-api.greenhouse.io/v1/boards/acme/jobs/42"


def test_to_vacancy_record_maps_all_fields():
    raw = RawGreenhouseJob.from_api({
        "id": 42, "title": " Backend  Engineer ",
        "absolute_url": "https://boards.greenhouse.io/acme/jobs/42/?gh_src=x",
        "location": {"name": "Remote - EU"},
    })
    rec = to_vacancy_record(raw, "acme", "Acme Corp")
    assert rec.source == "greenhouse"
    assert rec.source_url == "https://boards-api.greenhouse.io/v1/boards/acme/jobs/42"
    assert rec.canonical_url == "https://boards.greenhouse.io/acme/jobs/42"
    assert rec.company == "Acme Corp"
    assert rec.normalized_company == "acme corp"
    assert rec.title == " Backend  Engineer "
    assert rec.normalized_title == "backend engineer"
    assert rec.location == "Remote - EU"
    assert rec.work_mode == "remote"
    assert rec.ats_family == "greenhouse"


# --- infer_work_mode_from_flags ---

def test_infer_work_mode_from_flags_workplace_type_remote():
    assert infer_work_mode_from_flags("Remote") == "remote"
    assert infer_work_mode_from_flags("REMOTE") == "remote"
    assert infer_work_mode_from_flags("Fully Remote") == "remote"


def test_infer_work_mode_from_flags_workplace_type_hybrid():
    assert infer_work_mode_from_flags("Hybrid") == "hybrid"
    assert infer_work_mode_from_flags("hybrid remote") == "hybrid"


def test_infer_work_mode_from_flags_workplace_type_onsite():
    assert infer_work_mode_from_flags("OnSite") == "onsite"
    assert infer_work_mode_from_flags("on-site") == "onsite"
    assert infer_work_mode_from_flags("on site") == "onsite"


def test_infer_work_mode_from_flags_is_remote_true():
    assert infer_work_mode_from_flags(None, is_remote=True) == "remote"
    assert infer_work_mode_from_flags("", is_remote=True) == "remote"


def test_infer_work_mode_from_flags_is_remote_false_with_location():
    assert infer_work_mode_from_flags(None, is_remote=False, location="Berlin") == "onsite"


def test_infer_work_mode_from_flags_fallback_to_infer():
    # нет флагов — fallback на infer_work_mode(location)
    assert infer_work_mode_from_flags(None, None, "Remote EU") == "remote"
    assert infer_work_mode_from_flags(None, None, "Berlin, Germany") == "onsite"
    assert infer_work_mode_from_flags(None, None, None) == "unknown"


# --- ashby_to_record ---

def test_ashby_to_record_remote_from_workplace_type():
    raw = RawAshbyJob.from_api({
        "id": "a1", "title": "SRE",
        "jobUrl": "https://jobs.ashbyhq.com/co/a1",
        "workplaceType": "Remote", "location": "Amsterdam",
    })
    rec = ashby_to_record(raw, "co", "Company")
    assert rec.source == "ashby"
    assert rec.ats_family == "ashby"
    assert rec.work_mode == "remote"
    assert rec.company == "Company"
    assert rec.normalized_company == "company"
    assert rec.title == "SRE"
    assert rec.normalized_title == "sre"
    assert rec.location == "Amsterdam"
    assert rec.canonical_url == "https://jobs.ashbyhq.com/co/a1"


def test_ashby_to_record_onsite_via_is_remote_false():
    raw = RawAshbyJob.from_api({
        "id": "a2", "title": "PM",
        "jobUrl": "https://jobs.ashbyhq.com/co/a2",
        "isRemote": False, "location": "Berlin",
    })
    rec = ashby_to_record(raw, "co", "Co")
    assert rec.work_mode == "onsite"


# --- lever_to_record ---

def test_lever_to_record_remote_from_location():
    raw = RawLeverJob.from_api({
        "id": "lv1", "text": "Backend Dev",
        "hostedUrl": "https://jobs.lever.co/co/lv1",
        "categories": {"location": "Remote", "team": "Eng", "commitment": "Full-time"},
    })
    rec = lever_to_record(raw, "co", "Lever Co")
    assert rec.source == "lever"
    assert rec.ats_family == "lever"
    assert rec.work_mode == "remote"
    assert rec.location == "Remote"
    assert rec.source_url == "https://api.lever.co/v0/postings/co/lv1"
    assert rec.canonical_url == "https://jobs.lever.co/co/lv1"


def test_lever_to_record_unknown_when_no_location():
    raw = RawLeverJob.from_api({
        "id": "lv2", "text": "PM",
        "hostedUrl": "https://jobs.lever.co/co/lv2",
    })
    rec = lever_to_record(raw, "co", "Co")
    assert rec.work_mode == "unknown"


# --- workable_to_record ---

def test_workable_to_record_maps_all_fields():
    raw = RawWorkableJob.from_api({
        "id": 5935463, "shortcode": "4BEEC303BF", "title": " QA Lead ",
        "remote": True, "workplace": "remote",
        "location": {"country": "Cyprus", "city": "Limassol"},
    })
    rec = workable_to_record(raw, "toloka-ai", "Toloka AI")
    assert rec.source == "workable"
    assert rec.ats_family == "workable"
    assert rec.source_url == \
        "https://apply.workable.com/api/v1/accounts/toloka-ai/jobs/4BEEC303BF"
    # canonicalize_url лоуэркейсит только scheme/host, НЕ path — shortcode сохраняет регистр
    assert rec.canonical_url == "https://apply.workable.com/toloka-ai/j/4BEEC303BF"
    assert rec.company == "Toloka AI"
    assert rec.normalized_company == "toloka ai"
    assert rec.title == " QA Lead "
    assert rec.normalized_title == "qa lead"
    assert rec.location == "Limassol, Cyprus"
    assert rec.work_mode == "remote"


def test_workable_to_record_onsite_when_remote_field_absent():
    # "remote" отсутствует в ответе API -> RawWorkableJob.remote = None (не False).
    # infer_work_mode_from_flags получает is_remote=None и уходит в fallback
    # на инференс по location_name, а не по явному remote=False.
    raw = RawWorkableJob.from_api({
        "id": 1, "shortcode": "X", "title": "Ops",
        "location": {"country": "Germany", "city": "Berlin"},
    })
    rec = workable_to_record(raw, "acme", "Acme")
    assert rec.work_mode == "onsite"


# --- recruitee_to_record ---

def test_recruitee_to_record_maps_all_fields():
    raw = RawRecruiteeJob.from_api({
        "id": 2384617, "slug": "qa-lead-cyprus", "title": "QA Lead",
        "careers_url": "https://career.example.com/o/qa-lead-cyprus",
        "location": "Limassol, Cyprus", "remote": True,
    })
    rec = recruitee_to_record(raw, "acme", "Acme")
    assert rec.source == "recruitee"
    assert rec.ats_family == "recruitee"
    assert rec.source_url == "https://acme.recruitee.com/api/offers/qa-lead-cyprus"
    assert rec.canonical_url == "https://career.example.com/o/qa-lead-cyprus"
    assert rec.location == "Limassol, Cyprus"
    assert rec.work_mode == "remote"


def test_recruitee_to_record_hybrid_flag():
    raw = RawRecruiteeJob.from_api({
        "id": 1, "slug": "x", "title": "X",
        "careers_url": "https://acme.recruitee.com/o/x",
        "hybrid": True, "location": "Berlin",
    })
    rec = recruitee_to_record(raw, "acme", "Acme")
    assert rec.work_mode == "hybrid"


def test_recruitee_to_record_remote_and_hybrid_true_prefers_remote():
    # Recruitee допускает оба флага true одновременно (не взаимоисключающие) —
    # remote приоритетнее hybrid в этом случае (см. комментарий в recruitee_to_record).
    raw = RawRecruiteeJob.from_api({
        "id": 1, "slug": "x", "title": "X",
        "careers_url": "https://acme.recruitee.com/o/x",
        "remote": True, "hybrid": True, "location": "Berlin",
    })
    rec = recruitee_to_record(raw, "acme", "Acme")
    assert rec.work_mode == "remote"


def test_recruitee_to_record_onsite_fallback_to_location():
    raw = RawRecruiteeJob.from_api({
        "id": 1, "slug": "x", "title": "X",
        "careers_url": "https://acme.recruitee.com/o/x",
        "location": "Berlin, Germany",
    })
    rec = recruitee_to_record(raw, "acme", "Acme")
    assert rec.work_mode == "onsite"


# --- smartrecruiters_to_record ---

def test_smartrecruiters_to_record_remote():
    raw = RawSmartRecruitersJob.from_api({
        "id": 744000137659849, "name": " QA Engineer ",
        "location": {"city": "Kyiv", "country": "ua", "remote": True},
    })
    rec = smartrecruiters_to_record(raw, "playtech", "Playtech")
    assert rec.source == "smartrecruiters"
    assert rec.ats_family == "smartrecruiters"
    assert rec.source_url == \
        "https://api.smartrecruiters.com/v1/companies/playtech/postings/744000137659849"
    assert rec.canonical_url == \
        "https://jobs.smartrecruiters.com/playtech/744000137659849"
    assert rec.company == "Playtech"
    assert rec.normalized_company == "playtech"
    assert rec.title == " QA Engineer "
    assert rec.normalized_title == "qa engineer"
    assert rec.location == "Kyiv, ua"
    assert rec.work_mode == "remote"


def test_smartrecruiters_to_record_hybrid_flag():
    raw = RawSmartRecruitersJob.from_api({
        "id": "1", "name": "X", "location": {"city": "Berlin", "hybrid": True},
    })
    rec = smartrecruiters_to_record(raw, "acme", "Acme")
    assert rec.work_mode == "hybrid"


def test_smartrecruiters_to_record_remote_and_hybrid_true_prefers_remote():
    raw = RawSmartRecruitersJob.from_api({
        "id": "1", "name": "X", "location": {"remote": True, "hybrid": True, "city": "Berlin"},
    })
    rec = smartrecruiters_to_record(raw, "acme", "Acme")
    assert rec.work_mode == "remote"


def test_smartrecruiters_to_record_onsite_fallback_to_location():
    raw = RawSmartRecruitersJob.from_api({
        "id": "1", "name": "X", "location": {"city": "Berlin", "country": "de"},
    })
    rec = smartrecruiters_to_record(raw, "acme", "Acme")
    assert rec.work_mode == "onsite"


# --- pinpoint_to_record ---

def test_pinpoint_to_record_remote():
    raw = RawPinpointJob.from_api({
        "id": 282412, "title": " QA Engineer ",
        "url": "https://acme.pinpointhq.com/en/postings/uuid-here",
        "location": {"name": "Remote"}, "workplace_type": "remote",
    })
    rec = pinpoint_to_record(raw, "acme", "Acme")
    assert rec.source == "pinpoint"
    assert rec.ats_family == "pinpoint"
    assert rec.source_url == "https://acme.pinpointhq.com/en/postings/uuid-here"
    assert rec.canonical_url == "https://acme.pinpointhq.com/en/postings/uuid-here"
    assert rec.company == "Acme"
    assert rec.normalized_company == "acme"
    assert rec.title == " QA Engineer "
    assert rec.normalized_title == "qa engineer"
    assert rec.location == "Remote"
    assert rec.work_mode == "remote"


def test_pinpoint_to_record_onsite_fallback_to_location():
    raw = RawPinpointJob.from_api({
        "id": "1", "title": "X", "url": "https://acme.pinpointhq.com/en/postings/x",
        "location": {"city": "Berlin"},
    })
    rec = pinpoint_to_record(raw, "acme", "Acme")
    assert rec.work_mode == "onsite"


def test_arbeitnow_to_record_remote():
    raw = RawArbeitnowJob.from_api({
        "slug": "a", "title": " QA Lead ", "url": "https://www.arbeitnow.com/jobs/acme/a",
        "company_name": "Acme", "remote": True, "location": "Berlin, Germany",
    })
    rec = arbeitnow_to_record(raw, "", None)
    assert rec.source == "arbeitnow"
    assert rec.ats_family == "arbeitnow"
    assert rec.source_url == "https://www.arbeitnow.com/jobs/acme/a"
    assert rec.company == "Acme"
    assert rec.normalized_company == "acme"
    assert rec.normalized_title == "qa lead"
    assert rec.work_mode == "remote"


def test_arbeitnow_to_record_onsite_without_remote_flag():
    raw = RawArbeitnowJob.from_api({
        "slug": "b", "title": "Ops", "url": "https://www.arbeitnow.com/jobs/acme/b",
        "location": "Berlin, Germany",
    })
    rec = arbeitnow_to_record(raw, "", None)
    assert rec.work_mode == "onsite"


def test_jobicy_to_record_always_remote():
    raw = RawJobicyJob.from_api({
        "id": 1, "url": "https://jobicy.com/jobs/1-qa", "jobTitle": " QA Lead ",
        "companyName": "Acme", "jobGeo": "Europe",
    })
    rec = jobicy_to_record(raw, "", None)
    assert rec.source == "jobicy"
    assert rec.company == "Acme"
    assert rec.location == "Europe"
    assert rec.work_mode == "remote"  # Jobicy — remote-only борд по определению


def test_himalayas_to_record_always_remote():
    raw = RawHimalayasJob.from_api({
        "title": " QA Lead ", "companyName": "Acme",
        "locationRestrictions": ["Cyprus", "Malta"],
        "applicationLink": "https://himalayas.app/companies/a/jobs/qa",
    })
    rec = himalayas_to_record(raw, "", None)
    assert rec.source == "himalayas"
    assert rec.location == "Cyprus, Malta"
    assert rec.work_mode == "remote"


def test_himalayas_to_record_no_location_restrictions():
    raw = RawHimalayasJob.from_api({
        "title": "X", "applicationLink": "https://himalayas.app/companies/a/jobs/x",
    })
    rec = himalayas_to_record(raw, "", None)
    assert rec.location is None


def test_remotive_to_record_always_remote():
    raw = RawRemotiveJob.from_api({
        "id": 1, "url": "https://remotive.com/remote-jobs/qa/1", "title": " QA Lead ",
        "company_name": "Acme", "candidate_required_location": "Europe",
    })
    rec = remotive_to_record(raw, "", None)
    assert rec.source == "remotive"
    assert rec.location == "Europe"
    assert rec.work_mode == "remote"


def test_djinni_to_record_unknown_work_mode_no_location():
    raw = RawDjinniJob.from_feed_item({
        "title": "QA Lead", "link": "https://djinni.co/jobs/1-qa-lead/",
    })
    rec = djinni_to_record(raw, "", None)
    assert rec.source == "djinni"
    assert rec.company is None
    assert rec.work_mode == "unknown"  # нет location-сигнала вовсе


def test_wwr_to_record_always_remote():
    raw = RawWwrJob.from_feed_item({
        "title": "Acme: QA Lead", "link": "https://weworkremotely.com/remote-jobs/1",
        "region": "Anywhere in the World",
    })
    rec = wwr_to_record(raw, "", None)
    assert rec.source == "weworkremotely"
    assert rec.company == "Acme"
    assert rec.title == "QA Lead"
    assert rec.work_mode == "remote"


def test_net_empregos_to_record_onsite_with_location():
    raw = RawNetEmpregosJob.from_feed_item({
        "title": "QA Lead", "creator": "Acme",
        "link": "https://www.net-empregos.com/1/qa-lead/",
        "description": "<b>Zona: </b>Lisboa<br>",
    })
    rec = net_empregos_to_record(raw, "", None)
    assert rec.source == "netempregos"
    assert rec.company == "Acme"
    assert rec.location == "Lisboa"


# --- kariera_to_record ---

def test_kariera_to_record_onsite_by_default():
    raw = RawKarieraJob.from_jsonld({
        "title": " QA Lead ", "hiringOrganization": {"name": "Acme"},
        "jobLocation": {"address": {"addressLocality": "Athens", "addressCountry": "Greece"}},
    }, page_url="https://www.kariera.gr/jobs/it-jobs/1")
    rec = kariera_to_record(raw, "", None)
    assert rec.source == "kariera"
    assert rec.company == "Acme"
    assert rec.location == "Athens, Greece"
    assert rec.work_mode == "onsite"


def test_kariera_to_record_remote_from_telecommute_flag():
    raw = RawKarieraJob.from_jsonld({
        "title": "X", "jobLocationType": "TELECOMMUTE",
    }, page_url="https://www.kariera.gr/jobs/it-jobs/2")
    rec = kariera_to_record(raw, "", None)
    assert rec.work_mode == "remote"


# --- landing_jobs_to_record ---

def test_landing_jobs_to_record_uses_company_slug_as_title_cased_name():
    raw = RawLandingJobsJob.from_api({
        "id": 1, "title": " QA Lead ", "remote": True,
        "url": "https://landing.jobs/at/damia-group-portugal/qa-lead",
        "locations": [{"city": "Lisbon", "country_code": "PT"}],
    })
    rec = landing_jobs_to_record(raw, "", None)
    assert rec.source == "landingjobs"
    assert rec.company == "Damia Group Portugal"
    assert rec.location == "Lisbon, PT"
    assert rec.work_mode == "remote"


def test_landing_jobs_to_record_onsite():
    raw = RawLandingJobsJob.from_api({
        "id": 2, "title": "X", "remote": False,
        "url": "https://landing.jobs/at/acme/x",
        "locations": [{"city": "Lisbon", "country_code": "PT"}],
    })
    rec = landing_jobs_to_record(raw, "", None)
    assert rec.work_mode == "onsite"


# --- hh_to_record ---

def test_hh_to_record_maps_remote_and_company():
    from job_machine.discovery.models import RawHhJob
    from job_machine.discovery.normalize import hh_to_record

    raw = RawHhJob(
        title="QA Lead",
        url="https://hh.ru/vacancy/1?query=QA+Lead",
        company_name="Valletta.Software",
        location="Мальта",
        is_remote=True,
    )
    rec = hh_to_record(raw, "qa-lead", None)
    assert rec.source == "hh"
    assert rec.source_url == raw.url
    assert rec.canonical_url == "https://hh.ru/vacancy/1"
    assert rec.company == "Valletta.Software"
    assert rec.normalized_company == "valletta.software"
    assert rec.title == "QA Lead"
    assert rec.location == "Мальта"
    assert rec.work_mode == "remote"
    assert rec.ats_family == "hh"


def test_hh_to_record_non_remote_card():
    from job_machine.discovery.models import RawHhJob
    from job_machine.discovery.normalize import hh_to_record

    raw = RawHhJob(title="Onsite QA", url="https://hh.ru/vacancy/2", is_remote=False)
    rec = hh_to_record(raw, "qa-lead", None)
    assert rec.work_mode == "unknown"
