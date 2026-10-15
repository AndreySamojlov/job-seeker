from job_machine.discovery.rss import parse_rss_items

DJINNI_SAMPLE = """<?xml version="1.0"?>
<rss><channel>
<item>
  <title>Head Hunting</title>
  <link>https://djinni.co/jobs/834380-head-hunting/</link>
  <description>&lt;p&gt;hi&lt;/p&gt;</description>
  <pubDate>Sun, 05 Jul 2026 13:02:59 +0300</pubDate>
  <guid>https://djinni.co/jobs/834380-head-hunting/</guid>
  <category>Head Chief</category>
  <category/>
</item>
</channel></rss>"""

NET_EMPREGOS_SAMPLE = """<?xml version="1.0"?>
<rss xmlns:dc="http://purl.org/dc/elements/1.1/"><channel>
<item>
  <title><![CDATA[Gestao de pacientes]]></title>
  <dc:creator><![CDATA[FIRST CLASS CLINIC LDA]]></dc:creator>
  <link>https://www.net-empregos.com/15660814/x/</link>
  <description><![CDATA[<b>Zona: </b>Lisboa<br>]]></description>
  <pubDate>Sun, 5 Jul 2026 00:00:00 GMT</pubDate>
  <guid>https://www.net-empregos.com/15660814/x/</guid>
</item>
</channel></rss>"""


def test_parse_rss_items_basic_fields():
    items = parse_rss_items(DJINNI_SAMPLE)
    assert len(items) == 1
    assert items[0]["title"] == "Head Hunting"
    assert items[0]["link"] == "https://djinni.co/jobs/834380-head-hunting/"


def test_parse_rss_items_keeps_first_non_empty_duplicate_tag():
    items = parse_rss_items(DJINNI_SAMPLE)
    assert items[0]["category"] == "Head Chief"  # второй пустой <category/> игнорируется


def test_parse_rss_items_strips_namespace_prefix():
    items = parse_rss_items(NET_EMPREGOS_SAMPLE)
    assert items[0]["creator"] == "FIRST CLASS CLINIC LDA"


def test_parse_rss_items_empty_feed():
    assert parse_rss_items("<?xml version=\"1.0\"?><rss><channel></channel></rss>") == []
