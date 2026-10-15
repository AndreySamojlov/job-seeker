import httpx

from job_machine.discovery.netempregos import (
    NET_EMPREGOS_RSS_URL,
    NET_EMPREGOS_USER_AGENT,
    NetEmpregosClient,
)

SAMPLE_RSS = """<?xml version="1.0"?>
<rss xmlns:dc="http://purl.org/dc/elements/1.1/"><channel>
<item>
  <title><![CDATA[QA Lead]]></title>
  <dc:creator><![CDATA[Acme]]></dc:creator>
  <link>https://www.net-empregos.com/1/qa-lead/</link>
  <description><![CDATA[<b>Zona: </b>Lisboa<br>]]></description>
  <guid>https://www.net-empregos.com/1/qa-lead/</guid>
</item>
</channel></rss>"""


def _client(handler) -> NetEmpregosClient:
    http = httpx.Client(transport=httpx.MockTransport(handler))
    return NetEmpregosClient(http_client=http)


def test_list_jobs_parses_feed():
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == NET_EMPREGOS_RSS_URL
        return httpx.Response(200, text=SAMPLE_RSS)

    c = _client(handler)
    jobs = c.list_jobs("")
    assert len(jobs) == 1
    assert jobs[0].company_name == "Acme"
    assert jobs[0].location == "Lisboa"


def test_check_job_live_and_gone():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=SAMPLE_RSS)

    c = _client(handler)
    assert c.check_job("https://www.net-empregos.com/1/qa-lead/") == "live"
    assert c.check_job("https://www.net-empregos.com/2/gone/") == "gone"


def test_fetch_content_from_cache():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=SAMPLE_RSS)

    c = _client(handler)
    assert c.fetch_content("https://www.net-empregos.com/1/qa-lead/") == "<b>Zona: </b>Lisboa<br>"


def test_list_jobs_sends_identifying_user_agent():
    """WAF net-empregos.com сбрасывает соединение (TLS RST) для запросов с
    дефолтным User-Agent httpx/curl — воспроизведено на lab-do 2026-07-20.
    Честный self-identifying UA (как у harvest.py/manual.py) проходит."""
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["ua"] = request.headers.get("user-agent")
        return httpx.Response(200, text=SAMPLE_RSS)

    c = _client(handler)
    c.list_jobs("")
    assert captured["ua"] == NET_EMPREGOS_USER_AGENT


def test_check_job_caches_fetch_failure_without_repeating_network_calls():
    """Батч run_verify держит один NetEmpregosClient на все ~771 netempregos-
    вакансии в очереди (service.py кэширует клиент per ats_family). Раньше
    неудачный fetch НЕ кэшировался — каждый следующий check_job в том же батче
    заново гонял list_jobs() (3 попытки request_with_retry), превращая один сбой
    в сотни повторных сетевых попыток и раздувая длительность батча далеко за
    внешний таймаут вызова (симптом: 'ни одна запись не коммитится за вызов')."""
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(1)
        raise httpx.ConnectError("boom", request=req)

    c = _client(handler)
    assert c.check_job("https://www.net-empregos.com/1/qa-lead/") == "error"
    calls_after_first = len(calls)
    assert calls_after_first > 0

    assert c.check_job("https://www.net-empregos.com/2/other/") == "error"
    assert len(calls) == calls_after_first


def test_check_job_handles_non_xml_200_response():
    """200 с телом не-RSS (WAF-заглушка/maintenance-страница) — ET.fromstring
    внутри parse_rss_items кидает xml.etree.ElementTree.ParseError, который НЕ
    является httpx.HTTPError. Раньше это пробрасывалось необработанным через
    check_job() наверх в service.run_verify(), где вызов check_client.check_job
    ничем не обёрнут — уронило бы весь батч без единого коммита тем же способом,
    что и сетевой сбой (см. test_check_job_caches_fetch_failure_...)."""
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(
            200,
            text='<!DOCTYPE html><html><head><meta charset="utf-8">'
                 "</head><body>Just a moment...&nbsp;<br></body></html>",
        )

    c = _client(handler)
    assert c.check_job("https://www.net-empregos.com/1/qa-lead/") == "error"
    calls_after_first = len(calls)
    assert calls_after_first > 0

    assert c.check_job("https://www.net-empregos.com/2/other/") == "error"
    assert len(calls) == calls_after_first
