import httpx

from job_machine.discovery.djinni import DJINNI_RSS_URL, DjinniClient

SAMPLE_RSS = """<?xml version="1.0"?>
<rss><channel>
<item>
  <title>QA Lead</title>
  <link>https://djinni.co/jobs/1-qa-lead/</link>
  <description>&lt;p&gt;hi&lt;/p&gt;</description>
  <guid>https://djinni.co/jobs/1-qa-lead/</guid>
</item>
</channel></rss>"""


def _client(handler) -> DjinniClient:
    http = httpx.Client(transport=httpx.MockTransport(handler))
    return DjinniClient(http_client=http)


def test_list_jobs_parses_feed():
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == DJINNI_RSS_URL
        return httpx.Response(200, text=SAMPLE_RSS)

    c = _client(handler)
    jobs = c.list_jobs("")
    assert len(jobs) == 1
    assert jobs[0].title == "QA Lead"


def test_get_board_name_returns_none():
    c = _client(lambda r: httpx.Response(200, text="<rss><channel></channel></rss>"))
    assert c.get_board_name("") is None


def test_check_job_live_and_gone():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=SAMPLE_RSS)

    c = _client(handler)
    assert c.check_job("https://djinni.co/jobs/1-qa-lead/") == "live"
    assert c.check_job("https://djinni.co/jobs/2-gone/") == "gone"


def test_fetch_content_from_cache():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=SAMPLE_RSS)

    c = _client(handler)
    assert c.fetch_content("https://djinni.co/jobs/1-qa-lead/") == "<p>hi</p>"
