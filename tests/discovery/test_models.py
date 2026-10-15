import pytest

from job_machine.discovery.models import (
    RawArbeitnowJob, RawAshbyJob, RawDjinniJob, RawGreenhouseJob, RawHhJob, RawHimalayasJob,
    RawJobicyJob, RawKarieraJob, RawLandingJobsJob, RawLeverJob, RawNetEmpregosJob,
    RawPinpointJob, RawRecruiteeJob, RawRemotiveJob, RawSmartRecruitersJob, RawWorkableJob,
    RawWwrJob, VacancyRecord,
)


def test_raw_from_api_pulls_nested_location():
    raw = RawGreenhouseJob.from_api({
        "id": 42, "title": "Backend Engineer",
        "absolute_url": "https://boards.greenhouse.io/acme/jobs/42",
        "location": {"name": "Remote - EU"}, "updated_at": "2026-06-01T00:00:00Z",
    })
    assert raw.id == 42
    assert raw.title == "Backend Engineer"
    assert raw.location_name == "Remote - EU"


def test_raw_from_api_tolerates_missing_location():
    raw = RawGreenhouseJob.from_api({
        "id": 1, "title": "X", "absolute_url": "https://boards.greenhouse.io/acme/jobs/1",
    })
    assert raw.location_name is None


def test_vacancy_record_required_fields():
    rec = VacancyRecord(
        source="greenhouse", source_url="u", canonical_url="c",
        company="Acme", normalized_company="acme", title="X",
        normalized_title="x", location="Remote", work_mode="remote",
        ats_family="greenhouse",
    )
    assert rec.ats_family == "greenhouse"


# --- RawAshbyJob ---

def test_ashby_from_api_uses_apply_url():
    raw = RawAshbyJob.from_api({
        "id": "abc-123", "title": "Staff Engineer",
        "applyUrl": "https://jobs.ashbyhq.com/acme/abc-123/application",
        "jobUrl": "https://jobs.ashbyhq.com/acme/abc-123",
        "location": "Amsterdam", "workplaceType": "Hybrid",
        "isRemote": False,
        "secondaryLocations": [{"location": "Berlin"}, {"location": "London"}],
    })
    assert raw.id == "abc-123"
    assert raw.title == "Staff Engineer"
    assert raw.apply_url == "https://jobs.ashbyhq.com/acme/abc-123/application"
    assert raw.location == "Amsterdam"
    assert raw.workplace_type == "Hybrid"
    assert raw.is_remote is False
    assert raw.secondary_locations == ["Berlin", "London"]


def test_ashby_from_api_falls_back_to_job_url_when_no_apply_url():
    raw = RawAshbyJob.from_api({
        "id": "xyz", "title": "SRE",
        "jobUrl": "https://jobs.ashbyhq.com/acme/xyz",
    })
    assert raw.apply_url == "https://jobs.ashbyhq.com/acme/xyz"
    assert raw.secondary_locations == []
    assert raw.is_remote is None


def test_ashby_from_api_handles_null_secondary_locations():
    raw = RawAshbyJob.from_api({
        "id": "q", "title": "PM",
        "jobUrl": "https://jobs.ashbyhq.com/acme/q",
        "secondaryLocations": None,
    })
    assert raw.secondary_locations == []


def test_ashby_from_api_skips_secondary_entries_without_location():
    raw = RawAshbyJob.from_api({
        "id": "q", "title": "PM",
        "jobUrl": "https://jobs.ashbyhq.com/acme/q",
        "secondaryLocations": [{"foo": "bar"}, {"location": "Paris"}],
    })
    assert raw.secondary_locations == ["Paris"]


# --- RawLeverJob ---

def test_lever_from_api_full():
    raw = RawLeverJob.from_api({
        "id": "lever-111",
        "text": "Senior Backend Engineer",
        "hostedUrl": "https://jobs.lever.co/acme/lever-111",
        "applyUrl": "https://jobs.lever.co/acme/lever-111/apply",
        "categories": {
            "location": "Remote - Europe",
            "team": "Engineering",
            "commitment": "Full-time",
        },
        "workplaceType": "remote",
    })
    assert raw.id == "lever-111"
    assert raw.title == "Senior Backend Engineer"
    assert raw.hosted_url == "https://jobs.lever.co/acme/lever-111"
    assert raw.apply_url == "https://jobs.lever.co/acme/lever-111/apply"
    assert raw.location == "Remote - Europe"
    assert raw.team == "Engineering"
    assert raw.commitment == "Full-time"
    assert raw.workplace_type == "remote"


def test_lever_from_api_tolerates_missing_optional_fields():
    raw = RawLeverJob.from_api({
        "id": "lever-222",
        "text": "Data Engineer",
        "hostedUrl": "https://jobs.lever.co/acme/lever-222",
    })
    assert raw.apply_url is None
    assert raw.location is None
    assert raw.team is None
    assert raw.commitment is None
    assert raw.workplace_type is None


def test_lever_from_api_tolerates_null_categories():
    raw = RawLeverJob.from_api({
        "id": "lever-333", "text": "QA",
        "hostedUrl": "https://jobs.lever.co/acme/lever-333",
        "categories": None,
    })
    assert raw.location is None


# --- RawWorkableJob ---

def test_workable_from_api_full():
    raw = RawWorkableJob.from_api({
        "id": 5935463, "shortcode": "4BEEC303BF",
        "title": "Compliance Analyst - Freelance AI Trainer",
        "remote": True, "workplace": "remote",
        "location": {"country": "United States", "countryCode": "US", "city": "Austin"},
    })
    assert raw.id == 5935463
    assert raw.shortcode == "4BEEC303BF"
    assert raw.title == "Compliance Analyst - Freelance AI Trainer"
    assert raw.remote is True
    assert raw.workplace == "remote"
    assert raw.location_name == "Austin, United States"


def test_workable_from_api_tolerates_missing_location_and_workplace():
    raw = RawWorkableJob.from_api({
        "id": 1, "shortcode": "ABC", "title": "X",
    })
    assert raw.location_name is None
    assert raw.workplace is None
    assert raw.remote is None  # неизвестно (в отличие от явного remote:false) — как Ashby.is_remote


def test_workable_from_api_location_without_city():
    raw = RawWorkableJob.from_api({
        "id": 1, "shortcode": "ABC", "title": "X",
        "location": {"country": "Cyprus", "city": ""},
    })
    assert raw.location_name == "Cyprus"


# --- RawRecruiteeJob ---

def test_recruitee_from_api_full():
    raw = RawRecruiteeJob.from_api({
        "id": 2384617, "slug": "qa-lead-cyprus", "title": "QA Lead",
        "careers_url": "https://career.example.com/o/qa-lead-cyprus",
        "location": "Limassol, Cyprus", "remote": True, "hybrid": False,
    })
    assert raw.id == 2384617
    assert raw.slug == "qa-lead-cyprus"
    assert raw.title == "QA Lead"
    assert raw.careers_url == "https://career.example.com/o/qa-lead-cyprus"
    assert raw.location == "Limassol, Cyprus"
    assert raw.remote is True
    assert raw.hybrid is False


def test_recruitee_from_api_tolerates_missing_optional_fields():
    raw = RawRecruiteeJob.from_api({
        "id": 1, "slug": "x", "title": "X",
        "careers_url": "https://c.recruitee.com/o/x",
    })
    assert raw.location is None
    assert raw.remote is False
    assert raw.hybrid is False


# --- RawSmartRecruitersJob ---

def test_raw_smartrecruiters_job_from_api_maps_fields():
    raw = RawSmartRecruitersJob.from_api({
        "id": 744000137659849, "name": "QA Engineer",
        "location": {"city": "Kyiv", "country": "ua", "remote": False, "hybrid": True},
    })
    assert raw.id == "744000137659849"
    assert raw.title == "QA Engineer"
    assert raw.location_name == "Kyiv, ua"
    assert raw.remote is False
    assert raw.hybrid is True


def test_raw_smartrecruiters_job_from_api_missing_location():
    raw = RawSmartRecruitersJob.from_api({"id": "1", "name": "PM", "location": {}})
    assert raw.location_name is None
    assert raw.remote is None
    assert raw.hybrid is None


def test_raw_smartrecruiters_job_from_api_falls_back_to_full_location():
    raw = RawSmartRecruitersJob.from_api({
        "id": "1", "name": "PM", "location": {"fullLocation": "Remote, Worldwide"},
    })
    assert raw.location_name == "Remote, Worldwide"


# --- RawPinpointJob ---

def test_raw_pinpoint_job_from_api_maps_fields():
    raw = RawPinpointJob.from_api({
        "id": 282412, "title": "QA Engineer",
        "url": "https://acme.pinpointhq.com/en/postings/uuid-here",
        "description": "<p>hi</p>",
        "location": {"name": "Remote", "city": "Limassol"},
        "workplace_type": "remote",
    })
    assert raw.id == "282412"
    assert raw.title == "QA Engineer"
    assert raw.url == "https://acme.pinpointhq.com/en/postings/uuid-here"
    assert raw.description == "<p>hi</p>"
    assert raw.location_name == "Remote"
    assert raw.workplace_type == "remote"


def test_raw_pinpoint_job_from_api_location_falls_back_to_city():
    raw = RawPinpointJob.from_api({
        "id": "1", "title": "X", "url": "https://acme.pinpointhq.com/en/postings/x",
        "location": {"city": "Berlin"},
    })
    assert raw.location_name == "Berlin"


def test_raw_pinpoint_job_from_api_missing_optional_fields():
    raw = RawPinpointJob.from_api({
        "id": "1", "title": "X", "url": "https://acme.pinpointhq.com/en/postings/x",
    })
    assert raw.description is None
    assert raw.location_name is None
    assert raw.workplace_type is None


def test_arbeitnow_from_api_full():
    raw = RawArbeitnowJob.from_api({
        "slug": "qa-lead-acme", "title": "QA Lead",
        "company_name": "Acme", "description": "<p>hi</p>",
        "remote": True, "url": "https://www.arbeitnow.com/jobs/acme/qa-lead-acme",
        "tags": ["qa", "automation"], "location": "Berlin, Germany",
    })
    assert raw.slug == "qa-lead-acme"
    assert raw.company_name == "Acme"
    assert raw.remote is True
    assert raw.location == "Berlin, Germany"
    assert raw.tags == ["qa", "automation"]


def test_arbeitnow_from_api_tolerates_missing_optional_fields():
    raw = RawArbeitnowJob.from_api({
        "slug": "x", "title": "X", "url": "https://www.arbeitnow.com/jobs/x/x",
    })
    assert raw.company_name is None
    assert raw.remote is None
    assert raw.tags == []
    assert raw.location is None


def test_jobicy_from_api_full():
    raw = RawJobicyJob.from_api({
        "id": 123, "url": "https://jobicy.com/jobs/123-qa-lead",
        "jobTitle": "QA Lead", "companyName": "Acme", "jobGeo": "Europe",
        "jobDescription": "<p>hi</p>", "pubDate": "2026-07-05 10:00:00",
    })
    assert raw.id == 123
    assert raw.job_title == "QA Lead"
    assert raw.company_name == "Acme"
    assert raw.job_geo == "Europe"


def test_jobicy_from_api_tolerates_missing_optional_fields():
    raw = RawJobicyJob.from_api({"id": 1, "url": "https://jobicy.com/jobs/1-x", "jobTitle": "X"})
    assert raw.company_name is None
    assert raw.job_geo is None
    assert raw.description is None


def test_himalayas_from_api_full():
    raw = RawHimalayasJob.from_api({
        "title": "QA Lead", "excerpt": "short blurb", "companyName": "Acme",
        "locationRestrictions": ["Cyprus", "Malta"],
        "applicationLink": "https://himalayas.app/companies/acme/jobs/qa-lead",
        "guid": "https://himalayas.app/companies/acme/jobs/qa-lead",
    })
    assert raw.title == "QA Lead"
    assert raw.company_name == "Acme"
    assert raw.location_restrictions == ["Cyprus", "Malta"]
    assert raw.application_link == "https://himalayas.app/companies/acme/jobs/qa-lead"


def test_himalayas_from_api_tolerates_missing_optional_fields():
    raw = RawHimalayasJob.from_api({
        "title": "X", "applicationLink": "https://himalayas.app/companies/x/jobs/x",
    })
    assert raw.company_name is None
    assert raw.location_restrictions == []
    assert raw.excerpt is None


def test_remotive_from_api_full():
    raw = RawRemotiveJob.from_api({
        "id": 1, "url": "https://remotive.com/remote-jobs/qa/qa-lead-123",
        "title": "QA Lead", "company_name": "Acme",
        "candidate_required_location": "Europe", "description": "<p>hi</p>",
    })
    assert raw.id == 1
    assert raw.company_name == "Acme"
    assert raw.location == "Europe"


def test_remotive_from_api_tolerates_missing_optional_fields():
    raw = RawRemotiveJob.from_api({
        "id": 1, "url": "https://remotive.com/remote-jobs/qa/x", "title": "X",
    })
    assert raw.company_name is None
    assert raw.location is None
    assert raw.description is None


# --- RawDjinniJob ---

def test_djinni_from_feed_item_full():
    raw = RawDjinniJob.from_feed_item({
        "title": "Head Hunting", "link": "https://djinni.co/jobs/834380-head-hunting/",
        "description": "<p>hi</p>", "guid": "https://djinni.co/jobs/834380-head-hunting/",
    })
    assert raw.title == "Head Hunting"
    assert raw.link == "https://djinni.co/jobs/834380-head-hunting/"
    assert raw.description == "<p>hi</p>"
    assert raw.company_name is None  # Djinni RSS не отдаёт company — задокументировано


# --- RawWwrJob ---

def test_wwr_from_feed_item_splits_company_from_title():
    raw = RawWwrJob.from_feed_item({
        "title": "Aventra Media: Performance Marketing Specialist",
        "link": "https://weworkremotely.com/remote-jobs/aventra-media-performance-marketing-specialist",
        "description": "<p>hi</p>", "region": "Anywhere in the World",
    })
    assert raw.company_name == "Aventra Media"
    assert raw.title == "Performance Marketing Specialist"
    assert raw.location == "Anywhere in the World"


def test_wwr_from_feed_item_no_colon_in_title():
    raw = RawWwrJob.from_feed_item({
        "title": "Executive Director", "link": "https://weworkremotely.com/remote-jobs/x",
    })
    assert raw.company_name is None
    assert raw.title == "Executive Director"


# --- RawNetEmpregosJob ---

def test_net_empregos_from_feed_item_extracts_location_from_description():
    raw = RawNetEmpregosJob.from_feed_item({
        "title": "Gestao de pacientes", "creator": "FIRST CLASS CLINIC LDA",
        "link": "https://www.net-empregos.com/15660814/x/",
        "description": "<b>Empresa: </b>X<br><b>Categoria: </b>Y<br>"
                        "<b>Zona: </b> Lisboa<br><b>Data: </b>5-7-2026<br>",
    })
    assert raw.company_name == "FIRST CLASS CLINIC LDA"
    assert raw.location == "Lisboa"


def test_net_empregos_from_feed_item_no_zona_in_description():
    raw = RawNetEmpregosJob.from_feed_item({
        "title": "X", "link": "https://www.net-empregos.com/1/x/", "description": "sem zona aqui",
    })
    assert raw.location is None


def test_net_empregos_from_feed_item_extracts_location_from_double_escaped_description():
    """Живой фид Net-Empregos double-encode-ит HTML даже внутри CDATA
    (&lt;b&gt; вместо буквального <b>) — подтверждено прямым curl 2026-07-05.
    Regex должен матчить и после unescape, не только на «чистых» фикстурах."""
    raw = RawNetEmpregosJob.from_feed_item({
        "title": "Assistente", "creator": "Clan",
        "link": "https://www.net-empregos.com/15660969/x/",
        "description": "&lt;b&gt;Empresa: &lt;/b&gt;Clan&lt;br&gt;"
                        "&lt;b&gt;Categoria: &lt;/b&gt;Manutencao&lt;br&gt;"
                        "&lt;b&gt;Zona: &lt;/b&gt; Porto&lt;br&gt;"
                        "&lt;b&gt;Data: &lt;/b&gt;5-7-2026&lt;br&gt;",
    })
    assert raw.location == "Porto"


# --- RawKarieraJob ---

def test_kariera_from_jsonld_full():
    raw = RawKarieraJob.from_jsonld({
        "title": "Software Quality Assurance Engineer",
        "description": "<p>hi</p>",
        "hiringOrganization": {"name": "Acme"},
        "jobLocation": {"address": {"addressLocality": "Mandra", "addressCountry": "Greece"}},
        "url": "https://www.kariera.gr/jobs/it-jobs/249479",
    }, page_url="https://www.kariera.gr/jobs/it-jobs/249479")
    assert raw.title == "Software Quality Assurance Engineer"
    assert raw.company_name == "Acme"
    assert raw.location_name == "Mandra, Greece"
    assert raw.job_location_type is None


def test_kariera_from_jsonld_telecommute_flag():
    raw = RawKarieraJob.from_jsonld({
        "title": "X", "jobLocationType": "TELECOMMUTE",
    }, page_url="https://www.kariera.gr/jobs/it-jobs/1")
    assert raw.job_location_type == "TELECOMMUTE"


def test_kariera_from_jsonld_falls_back_to_page_url():
    raw = RawKarieraJob.from_jsonld({"title": "X"}, page_url="https://www.kariera.gr/jobs/it-jobs/1")
    assert raw.url == "https://www.kariera.gr/jobs/it-jobs/1"


# --- RawLandingJobsJob ---

def test_landing_jobs_from_api_extracts_company_from_url():
    raw = RawLandingJobsJob.from_api({
        "id": 1, "title": "Senior Java Developer", "remote": False,
        "url": "https://landing.jobs/at/inscale/senior-java-developer-in-lisbon-2025",
        "locations": [{"city": "Lisbon", "country_code": "PT"}],
        "role_description": "<p>hi</p>",
    })
    assert raw.title == "Senior Java Developer"
    assert raw.company_slug == "inscale"
    assert raw.remote is False
    assert raw.location_names == ["Lisbon, PT"]


def test_landing_jobs_from_api_tolerates_missing_optional_fields():
    raw = RawLandingJobsJob.from_api({
        "id": 2, "title": "X", "url": "https://landing.jobs/at/acme/x",
    })
    assert raw.remote is False
    assert raw.location_names == []
    assert raw.description is None


def test_landing_jobs_from_api_no_at_segment_in_url():
    raw = RawLandingJobsJob.from_api({
        "id": 3, "title": "X", "url": "https://landing.jobs/jobs/3",
    })
    assert raw.company_slug is None


# --- RawHhJob ---

def test_raw_hh_job_basic_fields():
    job = RawHhJob(
        title="QA Lead",
        url="https://hh.ru/vacancy/135084322?query=QA+Lead",
        company_name="Valletta.Software",
        location="Мальта",
        is_remote=True,
    )
    assert job.title == "QA Lead"
    assert job.company_name == "Valletta.Software"
    assert job.is_remote is True


def test_raw_hh_job_defaults_when_optional_fields_omitted():
    from job_machine.discovery.models import RawHhJob

    job = RawHhJob(title="X", url="https://hh.ru/vacancy/1")
    assert job.company_name is None
    assert job.location is None
    assert job.is_remote is False
