import httpx

from job_machine.discovery.weworkremotely import WWR_RSS_URL, WwrClient

SAMPLE_RSS = """<?xml version="1.0"?>
<rss><channel>
<item>
  <title>Acme: QA Lead</title>
  <link>https://weworkremotely.com/remote-jobs/1-qa-lead</link>
  <region>Anywhere in the World</region>
  <description>&lt;p&gt;hi&lt;/p&gt;</description>
  <guid>https://weworkremotely.com/remote-jobs/1-qa-lead</guid>
</item>
</channel></rss>"""


def _client(handler) -> WwrClient:
    http = httpx.Client(transport=httpx.MockTransport(handler))
    return WwrClient(http_client=http)


def test_list_jobs_parses_feed():
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == WWR_RSS_URL
        return httpx.Response(200, text=SAMPLE_RSS)

    c = _client(handler)
    jobs = c.list_jobs("")
    assert len(jobs) == 1
    assert jobs[0].company_name == "Acme"


def test_check_job_live_and_gone():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=SAMPLE_RSS)

    c = _client(handler)
    assert c.check_job("https://weworkremotely.com/remote-jobs/1-qa-lead") == "live"
    assert c.check_job("https://weworkremotely.com/remote-jobs/2-gone") == "gone"


def test_fetch_content_from_cache():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=SAMPLE_RSS)

    c = _client(handler)
    assert c.fetch_content("https://weworkremotely.com/remote-jobs/1-qa-lead") == "<p>hi</p>"
