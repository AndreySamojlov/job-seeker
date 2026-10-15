import html
import re

from pydantic import BaseModel


class RawAshbyJob(BaseModel):
    id: str
    title: str
    apply_url: str
    location: str | None = None
    workplace_type: str | None = None
    is_remote: bool | None = None
    secondary_locations: list[str] = []

    @classmethod
    def from_api(cls, data: dict) -> "RawAshbyJob":
        secondary = [
            s.get("location")
            for s in (data.get("secondaryLocations") or [])
            if isinstance(s, dict) and s.get("location")
        ]
        return cls(
            id=str(data["id"]),
            title=data["title"],
            apply_url=data.get("applyUrl") or data["jobUrl"],
            location=data.get("location"),
            workplace_type=data.get("workplaceType"),
            is_remote=data.get("isRemote"),
            secondary_locations=secondary,
        )


class RawLeverJob(BaseModel):
    id: str
    title: str
    hosted_url: str
    apply_url: str | None = None
    location: str | None = None
    team: str | None = None
    commitment: str | None = None
    workplace_type: str | None = None

    @classmethod
    def from_api(cls, data: dict) -> "RawLeverJob":
        cats = data.get("categories") or {}
        return cls(
            id=str(data["id"]),
            title=data["text"],
            hosted_url=data["hostedUrl"],
            apply_url=data.get("applyUrl"),
            location=cats.get("location"),
            team=cats.get("team"),
            commitment=cats.get("commitment"),
            workplace_type=data.get("workplaceType"),
        )


class RawGreenhouseJob(BaseModel):
    id: int
    title: str
    absolute_url: str
    location_name: str | None = None
    updated_at: str | None = None

    @classmethod
    def from_api(cls, data: dict) -> "RawGreenhouseJob":
        loc = data.get("location") or {}
        return cls(
            id=data["id"],
            title=data["title"],
            absolute_url=data["absolute_url"],
            location_name=loc.get("name"),
            updated_at=data.get("updated_at"),
        )


class RawWorkableJob(BaseModel):
    id: int
    shortcode: str
    title: str
    location_name: str | None = None
    workplace: str | None = None
    remote: bool | None = None  # None = поле отсутствует в ответе (как Ashby.is_remote)

    @classmethod
    def from_api(cls, data: dict) -> "RawWorkableJob":
        loc = data.get("location") or {}
        parts = [p for p in (loc.get("city"), loc.get("country")) if p]
        return cls(
            id=data["id"],
            shortcode=data["shortcode"],
            title=data["title"],
            location_name=", ".join(parts) if parts else None,
            workplace=data.get("workplace"),
            remote=data.get("remote"),
        )


class RawRecruiteeJob(BaseModel):
    id: int
    slug: str
    title: str
    careers_url: str
    location: str | None = None
    remote: bool = False
    hybrid: bool = False

    @classmethod
    def from_api(cls, data: dict) -> "RawRecruiteeJob":
        return cls(
            id=data["id"],
            slug=data["slug"],
            title=data["title"],
            careers_url=data["careers_url"],
            location=data.get("location"),
            remote=bool(data.get("remote", False)),
            hybrid=bool(data.get("hybrid", False)),
        )


class RawSmartRecruitersJob(BaseModel):
    id: str
    title: str
    location_name: str | None = None
    remote: bool | None = None
    hybrid: bool | None = None

    @classmethod
    def from_api(cls, data: dict) -> "RawSmartRecruitersJob":
        loc = data.get("location") or {}
        parts = [p for p in (loc.get("city"), loc.get("country")) if p]
        return cls(
            id=str(data["id"]),
            title=data["name"],
            location_name=", ".join(parts) if parts else loc.get("fullLocation"),
            remote=loc.get("remote"),
            hybrid=loc.get("hybrid"),
        )


class RawPinpointJob(BaseModel):
    id: str
    title: str
    url: str
    description: str | None = None
    location_name: str | None = None
    workplace_type: str | None = None

    @classmethod
    def from_api(cls, data: dict) -> "RawPinpointJob":
        loc = data.get("location") or {}
        return cls(
            id=str(data["id"]),
            title=data["title"],
            url=data["url"],
            description=data.get("description"),
            location_name=loc.get("name") or loc.get("city"),
            workplace_type=data.get("workplace_type"),
        )


class RawArbeitnowJob(BaseModel):
    slug: str
    title: str
    url: str
    company_name: str | None = None
    description: str | None = None
    remote: bool | None = None
    tags: list[str] = []
    location: str | None = None

    @classmethod
    def from_api(cls, data: dict) -> "RawArbeitnowJob":
        return cls(
            slug=data["slug"],
            title=data["title"],
            url=data["url"],
            company_name=data.get("company_name"),
            description=data.get("description"),
            remote=data.get("remote"),
            tags=data.get("tags") or [],
            location=data.get("location"),
        )


class RawJobicyJob(BaseModel):
    id: int
    url: str
    job_title: str
    company_name: str | None = None
    job_geo: str | None = None
    description: str | None = None

    @classmethod
    def from_api(cls, data: dict) -> "RawJobicyJob":
        return cls(
            id=data["id"],
            url=data["url"],
            job_title=data["jobTitle"],
            company_name=data.get("companyName"),
            job_geo=data.get("jobGeo"),
            description=data.get("jobDescription"),
        )


class RawHimalayasJob(BaseModel):
    title: str
    application_link: str
    company_name: str | None = None
    excerpt: str | None = None
    location_restrictions: list[str] = []

    @classmethod
    def from_api(cls, data: dict) -> "RawHimalayasJob":
        return cls(
            title=data["title"],
            application_link=data.get("applicationLink") or data["guid"],
            company_name=data.get("companyName"),
            excerpt=data.get("excerpt"),
            location_restrictions=data.get("locationRestrictions") or [],
        )


class RawRemotiveJob(BaseModel):
    id: int
    url: str
    title: str
    company_name: str | None = None
    location: str | None = None
    description: str | None = None

    @classmethod
    def from_api(cls, data: dict) -> "RawRemotiveJob":
        return cls(
            id=data["id"],
            url=data["url"],
            title=data["title"],
            company_name=data.get("company_name"),
            location=data.get("candidate_required_location"),
            description=data.get("description"),
        )


class RawDjinniJob(BaseModel):
    title: str
    link: str
    description: str | None = None
    company_name: str | None = None  # Djinni RSS не несёт company-поля — всегда None

    @classmethod
    def from_feed_item(cls, fields: dict) -> "RawDjinniJob":
        return cls(
            title=fields.get("title", ""),
            link=fields.get("link") or fields.get("guid", ""),
            description=fields.get("description"),
        )


class RawWwrJob(BaseModel):
    title: str
    link: str
    company_name: str | None = None
    description: str | None = None
    location: str | None = None

    @classmethod
    def from_feed_item(cls, fields: dict) -> "RawWwrJob":
        raw_title = fields.get("title", "")
        company_name = None
        title = raw_title
        if ": " in raw_title:
            company_name, title = raw_title.split(": ", 1)
        return cls(
            title=title,
            link=fields.get("link") or fields.get("guid", ""),
            company_name=company_name,
            description=fields.get("description"),
            location=fields.get("region") or fields.get("country") or fields.get("state"),
        )


class RawNetEmpregosJob(BaseModel):
    title: str
    link: str
    company_name: str | None = None
    description: str | None = None
    location: str | None = None

    @classmethod
    def from_feed_item(cls, fields: dict) -> "RawNetEmpregosJob":
        description = fields.get("description")
        location = None
        if description:
            match = re.search(r"Zona:\s*</b>\s*([^<]+?)\s*<br", html.unescape(description))
            if match:
                location = match.group(1).strip() or None
        return cls(
            title=fields.get("title", ""),
            link=fields.get("link") or fields.get("guid", ""),
            company_name=fields.get("creator"),
            description=description,
            location=location,
        )


class RawKarieraJob(BaseModel):
    url: str
    title: str
    description: str | None = None
    company_name: str | None = None
    location_name: str | None = None
    job_location_type: str | None = None

    @classmethod
    def from_jsonld(cls, data: dict, page_url: str) -> "RawKarieraJob":
        org = data.get("hiringOrganization") or {}
        addr = (data.get("jobLocation") or {}).get("address") or {}
        parts = [p for p in (addr.get("addressLocality"), addr.get("addressCountry")) if p]
        return cls(
            url=data.get("url") or page_url,
            title=data.get("title", ""),
            description=data.get("description"),
            company_name=org.get("name"),
            location_name=", ".join(parts) if parts else None,
            job_location_type=data.get("jobLocationType"),
        )


class RawLandingJobsJob(BaseModel):
    id: int
    title: str
    url: str
    company_slug: str | None = None
    remote: bool = False
    location_names: list[str] = []
    description: str | None = None

    @classmethod
    def from_api(cls, data: dict) -> "RawLandingJobsJob":
        match = re.search(r"/at/([^/]+)/", data["url"])
        locations = [
            f"{loc.get('city')}, {loc.get('country_code')}"
            for loc in (data.get("locations") or [])
            if loc.get("city") and loc.get("country_code")
        ]
        return cls(
            id=data["id"],
            title=data["title"],
            url=data["url"],
            company_slug=match.group(1) if match else None,
            remote=bool(data.get("remote", False)),
            location_names=locations,
            description=data.get("role_description"),
        )


class RawHhJob(BaseModel):
    """Карточка результата поиска hh.ru — конструируется напрямую regex-парсером
    (нет единого dict-payload для from_api, как у JSON-API источников)."""
    title: str
    url: str
    company_name: str | None = None
    location: str | None = None
    is_remote: bool = False


class VacancyRecord(BaseModel):
    source: str
    source_url: str
    canonical_url: str
    company: str | None
    normalized_company: str | None
    title: str
    normalized_title: str | None
    location: str | None
    work_mode: str
    ats_family: str
