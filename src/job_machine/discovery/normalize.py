import re

from job_machine.ats.urlnorm import normalize_apply_url
from job_machine.discovery.models import (
    RawArbeitnowJob, RawAshbyJob, RawDjinniJob, RawGreenhouseJob, RawHhJob, RawHimalayasJob,
    RawJobicyJob, RawKarieraJob, RawLandingJobsJob, RawLeverJob, RawNetEmpregosJob,
    RawPinpointJob, RawRecruiteeJob, RawRemotiveJob, RawSmartRecruitersJob, RawWorkableJob,
    RawWwrJob, VacancyRecord,
)

GH_API_BASE = "https://boards-api.greenhouse.io/v1/boards"
ASHBY_API_BASE = "https://api.ashbyhq.com/posting-api/job-board"
LEVER_API_BASE = "https://api.lever.co/v0/postings"
WORKABLE_DETAIL_BASE = "https://apply.workable.com/api/v1/accounts"
SMARTRECRUITERS_BASE = "https://api.smartrecruiters.com/v1/companies"


def canonicalize_url(url: str) -> str:
    """Канонизировать URL для дедупа. Единственная реализация — ats/urlnorm:
    дедуп discovery и destination-гейт fill/submit обязаны сходиться в том,
    «один ли это URL» (ревью среза: две копии нормализации дрейфуют)."""
    return normalize_apply_url(url)


def normalize_text(value: str | None) -> str | None:
    """Схлопнуть пробелы, casefold, пустую строку → None."""
    if value is None:
        return None
    collapsed = re.sub(r"\s+", " ", value).strip().casefold()
    return collapsed or None


def infer_work_mode(location_name: str | None) -> str:
    loc = (location_name or "").casefold()
    if "remote" in loc:
        return "remote"
    if "hybrid" in loc:
        return "hybrid"
    if loc.strip():
        return "onsite"
    return "unknown"


def infer_work_mode_from_flags(
    workplace_type: str | None,
    is_remote: bool | None = None,
    location: str | None = None,
) -> str:
    """Определить work_mode из структурированных флагов ATS (Ashby/Lever),
    с fallback на infer_work_mode по строке локации."""
    wt = (workplace_type or "").casefold()
    if "hybrid" in wt:
        return "hybrid"
    if "remote" in wt:
        return "remote"
    if "onsite" in wt or "on-site" in wt or "on site" in wt:
        return "onsite"
    if is_remote is True:
        return "remote"
    if is_remote is False and (location or "").strip():
        return "onsite"
    return infer_work_mode(location)


def ashby_to_record(
    raw: RawAshbyJob, board_token: str, board_name: str | None
) -> VacancyRecord:
    # source_url — Ashby JSON API endpoint (для verify check_job и fetch_content в
    # triage — оба рефетчат board-level листинг, per-job GET публично недоступен)
    # canonical_url — apply/hosted URL (только для дедупа; НЕ годится для verify —
    # jobs.ashbyhq.com отдаёт 200 даже на несуществующий job id, SPA)
    api_url = f"{ASHBY_API_BASE}/{board_token}/{raw.id}"
    return VacancyRecord(
        source="ashby",
        source_url=api_url,
        canonical_url=canonicalize_url(raw.apply_url),
        company=board_name,
        normalized_company=normalize_text(board_name),
        title=raw.title,
        normalized_title=normalize_text(raw.title),
        location=raw.location,
        work_mode=infer_work_mode_from_flags(raw.workplace_type, raw.is_remote, raw.location),
        ats_family="ashby",
    )


def lever_to_record(
    raw: RawLeverJob, board_token: str, board_name: str | None
) -> VacancyRecord:
    # source_url — Lever JSON API endpoint (для fetch_content в triage)
    # canonical_url — hosted URL (для дедупа и verify check_job)
    api_url = f"{LEVER_API_BASE}/{board_token}/{raw.id}"
    return VacancyRecord(
        source="lever",
        source_url=api_url,
        canonical_url=canonicalize_url(raw.hosted_url),
        company=board_name,
        normalized_company=normalize_text(board_name),
        title=raw.title,
        normalized_title=normalize_text(raw.title),
        location=raw.location,
        work_mode=infer_work_mode_from_flags(raw.workplace_type, None, raw.location),
        ats_family="lever",
    )


def api_job_url(board_token: str, job_id: int) -> str:
    return f"{GH_API_BASE}/{board_token}/jobs/{job_id}"


def to_vacancy_record(
    raw: RawGreenhouseJob, board_token: str, board_name: str | None
) -> VacancyRecord:
    return VacancyRecord(
        source="greenhouse",
        source_url=api_job_url(board_token, raw.id),
        canonical_url=canonicalize_url(raw.absolute_url),
        company=board_name,
        normalized_company=normalize_text(board_name),
        title=raw.title,
        normalized_title=normalize_text(raw.title),
        location=raw.location_name,
        work_mode=infer_work_mode(raw.location_name),
        ats_family="greenhouse",
    )


def workable_to_record(
    raw: RawWorkableJob, board_token: str, board_name: str | None
) -> VacancyRecord:
    # source_url — Workable detail API (для fetch_content в triage).
    # canonical_url — публичная apply-страница; API её не отдаёт явно, конструируем
    # по документированному паттерну (подтверждено живым GET, спека §7/§10).
    api_url = f"{WORKABLE_DETAIL_BASE}/{board_token}/jobs/{raw.shortcode}"
    apply_url = f"https://apply.workable.com/{board_token}/j/{raw.shortcode}/"
    return VacancyRecord(
        source="workable",
        source_url=api_url,
        canonical_url=canonicalize_url(apply_url),
        company=board_name,
        normalized_company=normalize_text(board_name),
        title=raw.title,
        normalized_title=normalize_text(raw.title),
        location=raw.location_name,
        work_mode=infer_work_mode_from_flags(raw.workplace, raw.remote, raw.location_name),
        ats_family="workable",
    )


def recruitee_to_record(
    raw: RawRecruiteeJob, board_token: str, board_name: str | None
) -> VacancyRecord:
    # source_url — Recruitee detail API на СВОЁМ поддомене (board_token), а не на
    # кастомном домене careers_url — они независимы (спека §10).
    api_url = f"https://{board_token}.recruitee.com/api/offers/{raw.slug}"
    # remote и hybrid — независимые булевы флаги, не взаимоисключающая категория;
    # Recruitee допускает оба true одновременно. В этом случае remote приоритетнее.
    if raw.remote:
        workplace_type = "remote"
    elif raw.hybrid:
        workplace_type = "hybrid"
    else:
        workplace_type = None
    return VacancyRecord(
        source="recruitee",
        source_url=api_url,
        canonical_url=canonicalize_url(raw.careers_url),
        company=board_name,
        normalized_company=normalize_text(board_name),
        title=raw.title,
        normalized_title=normalize_text(raw.title),
        location=raw.location,
        work_mode=infer_work_mode_from_flags(workplace_type, None, raw.location),
        ats_family="recruitee",
    )


def smartrecruiters_to_record(
    raw: RawSmartRecruitersJob, board_token: str, board_name: str | None
) -> VacancyRecord:
    # source_url — SmartRecruiters detail API (для fetch_content в triage).
    # canonical_url — публичная posting-страница без slug-суффикса; подтверждена
    # живым GET → 200 (SmartRecruiters не требует slug в URL, спека).
    api_url = f"{SMARTRECRUITERS_BASE}/{board_token}/postings/{raw.id}"
    posting_url = f"https://jobs.smartrecruiters.com/{board_token}/{raw.id}"
    # remote и hybrid — независимые булевы флаги (как Recruitee); remote приоритетнее.
    if raw.remote:
        workplace_type = "remote"
    elif raw.hybrid:
        workplace_type = "hybrid"
    else:
        workplace_type = None
    return VacancyRecord(
        source="smartrecruiters",
        source_url=api_url,
        canonical_url=canonicalize_url(posting_url),
        company=board_name,
        normalized_company=normalize_text(board_name),
        title=raw.title,
        normalized_title=normalize_text(raw.title),
        location=raw.location_name,
        work_mode=infer_work_mode_from_flags(workplace_type, location=raw.location_name),
        ats_family="smartrecruiters",
    )


def pinpoint_to_record(
    raw: RawPinpointJob, board_token: str, board_name: str | None
) -> VacancyRecord:
    # source_url == canonical_url — Pinpoint не отдаёт отдельного detail API;
    # fetch_content (pinpoint.py) переиспользует список и матчит по этому же url.
    return VacancyRecord(
        source="pinpoint",
        source_url=raw.url,
        canonical_url=canonicalize_url(raw.url),
        company=board_name,
        normalized_company=normalize_text(board_name),
        title=raw.title,
        normalized_title=normalize_text(raw.title),
        location=raw.location_name,
        work_mode=infer_work_mode_from_flags(raw.workplace_type, location=raw.location_name),
        ats_family="pinpoint",
    )


def arbeitnow_to_record(
    raw: RawArbeitnowJob, board_token: str, board_name: str | None
) -> VacancyRecord:
    # company — из ответа источника (Arbeitnow — кросс-компанийный агрегатор),
    # board_token/board_name НЕ используются (сигнатура унифицирована с ATS-
    # адаптерами ради нулевых изменений в диспатче service.py, спека §3).
    workplace_type = "remote" if raw.remote else None
    return VacancyRecord(
        source="arbeitnow",
        source_url=raw.url,
        canonical_url=canonicalize_url(raw.url),
        company=raw.company_name,
        normalized_company=normalize_text(raw.company_name),
        title=raw.title,
        normalized_title=normalize_text(raw.title),
        location=raw.location,
        work_mode=infer_work_mode_from_flags(workplace_type, raw.remote, raw.location),
        ats_family="arbeitnow",
    )


def jobicy_to_record(
    raw: RawJobicyJob, board_token: str, board_name: str | None
) -> VacancyRecord:
    return VacancyRecord(
        source="jobicy",
        source_url=raw.url,
        canonical_url=canonicalize_url(raw.url),
        company=raw.company_name,
        normalized_company=normalize_text(raw.company_name),
        title=raw.job_title,
        normalized_title=normalize_text(raw.job_title),
        location=raw.job_geo,
        work_mode="remote",
        ats_family="jobicy",
    )


def himalayas_to_record(
    raw: RawHimalayasJob, board_token: str, board_name: str | None
) -> VacancyRecord:
    location = ", ".join(raw.location_restrictions) if raw.location_restrictions else None
    return VacancyRecord(
        source="himalayas",
        source_url=raw.application_link,
        canonical_url=canonicalize_url(raw.application_link),
        company=raw.company_name,
        normalized_company=normalize_text(raw.company_name),
        title=raw.title,
        normalized_title=normalize_text(raw.title),
        location=location,
        work_mode="remote",
        ats_family="himalayas",
    )


def remotive_to_record(
    raw: RawRemotiveJob, board_token: str, board_name: str | None
) -> VacancyRecord:
    return VacancyRecord(
        source="remotive",
        source_url=raw.url,
        canonical_url=canonicalize_url(raw.url),
        company=raw.company_name,
        normalized_company=normalize_text(raw.company_name),
        title=raw.title,
        normalized_title=normalize_text(raw.title),
        location=raw.location,
        work_mode="remote",
        ats_family="remotive",
    )


def djinni_to_record(
    raw: RawDjinniJob, board_token: str, board_name: str | None
) -> VacancyRecord:
    return VacancyRecord(
        source="djinni",
        source_url=raw.link,
        canonical_url=canonicalize_url(raw.link),
        company=raw.company_name,
        normalized_company=normalize_text(raw.company_name),
        title=raw.title,
        normalized_title=normalize_text(raw.title),
        location=None,
        work_mode=infer_work_mode(None),
        ats_family="djinni",
    )


def wwr_to_record(
    raw: RawWwrJob, board_token: str, board_name: str | None
) -> VacancyRecord:
    return VacancyRecord(
        source="weworkremotely",
        source_url=raw.link,
        canonical_url=canonicalize_url(raw.link),
        company=raw.company_name,
        normalized_company=normalize_text(raw.company_name),
        title=raw.title,
        normalized_title=normalize_text(raw.title),
        location=raw.location,
        work_mode="remote",
        ats_family="weworkremotely",
    )


def net_empregos_to_record(
    raw: RawNetEmpregosJob, board_token: str, board_name: str | None
) -> VacancyRecord:
    return VacancyRecord(
        source="netempregos",
        source_url=raw.link,
        canonical_url=canonicalize_url(raw.link),
        company=raw.company_name,
        normalized_company=normalize_text(raw.company_name),
        title=raw.title,
        normalized_title=normalize_text(raw.title),
        location=raw.location,
        work_mode=infer_work_mode(raw.location),
        ats_family="netempregos",
    )


def kariera_to_record(
    raw: RawKarieraJob, board_token: str, board_name: str | None
) -> VacancyRecord:
    workplace_type = "remote" if (raw.job_location_type or "").upper() == "TELECOMMUTE" else None
    return VacancyRecord(
        source="kariera",
        source_url=raw.url,
        canonical_url=canonicalize_url(raw.url),
        company=raw.company_name,
        normalized_company=normalize_text(raw.company_name),
        title=raw.title,
        normalized_title=normalize_text(raw.title),
        location=raw.location_name,
        work_mode=infer_work_mode_from_flags(workplace_type, None, raw.location_name),
        ats_family="kariera",
    )


def landing_jobs_to_record(
    raw: RawLandingJobsJob, board_token: str, board_name: str | None
) -> VacancyRecord:
    company = raw.company_slug.replace("-", " ").title() if raw.company_slug else None
    location = ", ".join(raw.location_names) if raw.location_names else None
    workplace_type = "remote" if raw.remote else None
    return VacancyRecord(
        source="landingjobs",
        source_url=raw.url,
        canonical_url=canonicalize_url(raw.url),
        company=company,
        normalized_company=normalize_text(company),
        title=raw.title,
        normalized_title=normalize_text(raw.title),
        location=location,
        work_mode=infer_work_mode_from_flags(workplace_type, raw.remote, location),
        ats_family="landingjobs",
    )


def hh_to_record(
    raw: RawHhJob, board_token: str, board_name: str | None
) -> VacancyRecord:
    return VacancyRecord(
        source="hh",
        source_url=raw.url,
        canonical_url=canonicalize_url(raw.url),
        company=raw.company_name,
        normalized_company=normalize_text(raw.company_name),
        title=raw.title,
        normalized_title=normalize_text(raw.title),
        location=raw.location,
        work_mode="remote" if raw.is_remote else infer_work_mode(raw.location),
        ats_family="hh",
    )
