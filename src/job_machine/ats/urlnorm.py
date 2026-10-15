"""Нормализация apply-URL и идентичность requisition-поста (destination-контур §3).

Greenhouse редиректит локационные шарды requisition на канонический пост; вопрос
«тот же ли это пост» решается по (tenant, job_id) и игнорирует хост-вариации
(boards / job-boards / регион .eu), query/fragment и суффиксы пути после /jobs/<id>
(например /confirmation). Для прочих ATS — generic-нормализация URL."""
import re
from urllib.parse import parse_qs, urlsplit, urlunsplit

_GH_HOST = re.compile(r"^(?:job-)?boards(?:\.eu)?\.greenhouse\.io$")
_GH_PATH = re.compile(r"^/(?P<tenant>[^/]+)/jobs/(?P<job_id>\d+)")
_GH_EMBED_PATH = re.compile(r"^/embed/job_app/?$")


def normalize_apply_url(url: str) -> str:
    """Generic-канонизация: нижний регистр scheme/host, без query/fragment/хвостового слэша."""
    parts = urlsplit((url or "").strip())
    scheme = (parts.scheme or "https").lower()
    netloc = parts.netloc.lower()
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((scheme, netloc, path, "", ""))


def post_identity(url: str, ats_family: str | None = None) -> str:
    """Идентичность поста: greenhouse → 'gh:<tenant>:<job_id>', иначе normalized URL."""
    parts = urlsplit((url or "").strip())
    host = parts.netloc.lower()
    if _GH_HOST.match(host):
        m = _GH_PATH.match(parts.path)
        if m:
            return f"gh:{m.group('tenant').lower()}:{m.group('job_id')}"
        if _GH_EMBED_PATH.match(parts.path):
            q = parse_qs(parts.query)
            tenant = (q.get("for") or [""])[0].lower()
            token = (q.get("token") or [""])[0]
            if tenant and token:
                return f"gh:{tenant}:{token}"
    return normalize_apply_url(url)


def same_post(a: str, b: str, ats_family: str | None = None) -> bool:
    """Один и тот же requisition-пост? (сравнение идентичностей)"""
    return post_identity(a, ats_family) == post_identity(b, ats_family)


def identified_post(url: str, ats_family: str | None = None) -> bool:
    """URL позитивно идентифицирует пост (ATS-специфичный парс, не generic-фолбэк).

    Нужно для пост-submit инварианта: generic confirmation-URL (страница
    благодарности) не опровергает и не подтверждает destination — сравнивать нечего."""
    return post_identity(url, ats_family).startswith("gh:")


def confirmation_mismatch(confirmation_url: str | None, destination_url: str,
                          ats_family: str | None = None) -> bool:
    """Пост-submit инвариант: True только когда ОБА URL позитивно идентифицированы
    и указывают на РАЗНЫЕ посты. Пустой/generic confirmation ничего не доказывает —
    алерт на нём был бы шумом на каждом не-идентифицируемом ATS."""
    if not confirmation_url:
        return False
    if not (identified_post(confirmation_url, ats_family)
            and identified_post(destination_url, ats_family)):
        return False
    return not same_post(confirmation_url, destination_url, ats_family)
