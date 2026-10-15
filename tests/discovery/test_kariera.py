import httpx

from job_machine.discovery.kariera import KarieraClient

SITEMAP_INDEX = """<?xml version="1.0"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<sitemap><loc>https://www.kariera.gr/sitemaps/jobs-details/sitemap/0.xml</loc></sitemap>
<sitemap><loc>https://www.kariera.gr/sitemaps/companies/sitemap/0.xml</loc></sitemap>
</sitemapindex>"""

JOBS_SITEMAP = """<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>https://www.kariera.gr/jobs/it-jobs/1</loc></url>
</urlset>"""

JOB_PAGE_HTML = """<html><body>
<script type="application/ld+json">{"@context":"https://schema.org","@type":"JobPosting",
"title":"QA Lead","description":"<p>hi</p>","hiringOrganization":{"name":"Acme"}}</script>
</body></html>"""


def _client(handler) -> KarieraClient:
    http = httpx.Client(transport=httpx.MockTransport(handler))
    return KarieraClient(http_client=http, sleep=lambda *_: None)


def test_list_jobs_walks_sitemap_and_extracts_jsonld():
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == "https://www.kariera.gr/sitemap.xml":
            return httpx.Response(200, text=SITEMAP_INDEX)
        if url == "https://www.kariera.gr/sitemaps/jobs-details/sitemap/0.xml":
            return httpx.Response(200, text=JOBS_SITEMAP)
        if url == "https://www.kariera.gr/jobs/it-jobs/1":
            return httpx.Response(200, text=JOB_PAGE_HTML)
        return httpx.Response(404)

    c = _client(handler)
    jobs = c.list_jobs("")
    assert len(jobs) == 1
    assert jobs[0].title == "QA Lead"
    assert jobs[0].company_name == "Acme"


def test_list_jobs_skips_non_jobs_details_sitemaps():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if str(request.url) == "https://www.kariera.gr/sitemap.xml":
            return httpx.Response(200, text=SITEMAP_INDEX)
        return httpx.Response(200, text="<urlset></urlset>")

    c = _client(handler)
    c.list_jobs("")
    assert "https://www.kariera.gr/sitemaps/companies/sitemap/0.xml" not in calls


def test_check_job_live_and_gone():
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == "https://www.kariera.gr/jobs/it-jobs/1":
            return httpx.Response(200, text=JOB_PAGE_HTML)
        return httpx.Response(404)

    c = _client(handler)
    assert c.check_job("https://www.kariera.gr/jobs/it-jobs/1") == "live"
    assert c.check_job("https://www.kariera.gr/jobs/it-jobs/gone") == "gone"


def test_check_job_error_on_network():
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("timeout", request=req)

    c = _client(handler)
    assert c.check_job("https://www.kariera.gr/jobs/it-jobs/1") == "error"


def test_fetch_content_returns_description():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=JOB_PAGE_HTML)

    c = _client(handler)
    assert c.fetch_content("https://www.kariera.gr/jobs/it-jobs/1") == "<p>hi</p>"


def test_fetch_content_none_on_404():
    c = _client(lambda r: httpx.Response(404))
    assert c.fetch_content("https://www.kariera.gr/jobs/it-jobs/gone") is None


def test_check_job_finds_jobposting_after_other_jsonld_blocks():
    """Kariera.gr сейчас отдаёт ровно один JSON-LD блок на странице, но
    schema.org-страницы часто несут несколько (BreadcrumbList/Organization
    впереди JobPosting) — _extract_jsonld должен находить JobPosting, даже
    если он не первый блок на странице."""
    html_with_multiple_blocks = """<html><body>
<script type="application/ld+json">{"@context":"https://schema.org","@type":"BreadcrumbList","itemListElement":[]}</script>
<script type="application/ld+json">{"@context":"https://schema.org","@type":"JobPosting","title":"QA Lead","description":"<p>hi</p>","hiringOrganization":{"name":"Acme"}}</script>
</body></html>"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=html_with_multiple_blocks)

    c = _client(handler)
    assert c.check_job("https://www.kariera.gr/jobs/it-jobs/1") == "live"
    assert c.fetch_content("https://www.kariera.gr/jobs/it-jobs/1") == "<p>hi</p>"
