from job_machine.telegram_sourcing.parser import RawMessage, parse_messages

_SAMPLE_HTML = """
<div class="tgme_widget_message_wrap">
  <div class="tgme_widget_message" data-post="forallqa/101">
    <div class="tgme_widget_message_text js-message_text" dir="auto">
      QA Engineer &mdash; remote, Python/Selenium, 3+ years
    </div>
    <a class="tgme_widget_message_date" href="https://t.me/forallqa/101">
      <time datetime="2026-07-15T10:00:00+00:00">10:00</time>
    </a>
  </div>
</div>
<div class="tgme_widget_message_wrap">
  <div class="tgme_widget_message" data-post="forallqa/102">
    <div class="tgme_widget_message_text js-message_text" dir="auto">
      Senior <b>QA Automation</b> Engineer, Cyprus relocation
    </div>
    <a class="tgme_widget_message_date" href="https://t.me/forallqa/102">
      <time datetime="2026-07-15T11:30:00+00:00">11:30</time>
    </a>
  </div>
</div>
"""


def test_parse_messages_extracts_id_permalink_time_and_clean_text():
    out = parse_messages(_SAMPLE_HTML, "forallqa")
    assert out == [
        RawMessage(
            channel="forallqa", message_id=101,
            permalink="https://t.me/forallqa/101",
            posted_at="2026-07-15T10:00:00+00:00",
            text="QA Engineer — remote, Python/Selenium, 3+ years",
        ),
        RawMessage(
            channel="forallqa", message_id=102,
            permalink="https://t.me/forallqa/102",
            posted_at="2026-07-15T11:30:00+00:00",
            text="Senior QA Automation Engineer, Cyprus relocation",
        ),
    ]


def test_parse_messages_ignores_other_channels_in_same_page():
    # data-post from a different channel (forward/ad) must not appear in results
    html = _SAMPLE_HTML.replace('data-post="forallqa/102"', 'data-post="otherchan/999"')
    out = parse_messages(html, "forallqa")
    assert len(out) == 1
    assert out[0].message_id == 101


def test_parse_messages_empty_html_returns_empty_list():
    assert parse_messages("", "forallqa") == []


def test_parse_messages_no_matching_blocks_returns_empty_list():
    assert parse_messages("<html><body>private channel</body></html>", "forallqa") == []


def test_parse_messages_missing_time_or_text_is_tolerant():
    html = (
        '<div class="tgme_widget_message" data-post="forallqa/1">'
        "</div>"
    )
    out = parse_messages(html, "forallqa")
    assert out == [RawMessage(channel="forallqa", message_id=1,
                              permalink="https://t.me/forallqa/1",
                              posted_at=None, text="")]


def test_parse_messages_survives_nested_div_in_message_text():
    # A link in a job post triggers Telegram's own auto-embedded link-preview
    # <div> nested inside tgme_widget_message_text. A naive non-greedy
    # `(.*?)</div>` would stop at the FIRST </div> (the nested one) and
    # silently drop everything after it.
    html = """
    <div class="tgme_widget_message" data-post="forallqa/1">
      <div class="tgme_widget_message_text js-message_text" dir="auto">
        QA Engineer, remote. Apply:
        <div class="tgme_widget_message_link_preview">
          <div class="link_preview_title">Apply here</div>
        </div>
        Send CV to hr@example.com
      </div>
      <a class="tgme_widget_message_date" href="https://t.me/forallqa/1">
        <time datetime="2026-07-15T10:00:00+00:00">10:00</time>
      </a>
    </div>
    """
    out = parse_messages(html, "forallqa")
    assert len(out) == 1
    assert out[0].text == (
        "QA Engineer, remote. Apply: Apply here Send CV to hr@example.com"
    )
