import pytest

from job_machine.db import migrate
from job_machine.telegram_sourcing.channels import ChannelSpec
from job_machine.telegram_sourcing.service import run_fetch


def _apply_migrations(conn):
    for m in migrate.pending(migrate.discover_migrations("db/migrations"),
                             migrate.applied_migrations(conn)):
        migrate.apply_migration(conn, m)


_HTML = (
    '<div class="tgme_widget_message" data-post="{channel}/1">'
    '<div class="tgme_widget_message_text js-message_text">Role at {channel}</div>'
    '<time datetime="2026-07-15T10:00:00+00:00"></time>'
    '</div>'
)


class _FakeClient:
    def __init__(self, responses):
        self._responses = responses  # handle -> html | None | Exception instance
        self.calls = []

    def fetch_channel_html(self, handle):
        self.calls.append(handle)
        result = self._responses[handle]
        if isinstance(result, Exception):
            raise result
        return result


@pytest.mark.db
def test_run_fetch_inserts_leads_and_dedups_across_runs(db_schema):
    conn, _ = db_schema
    _apply_migrations(conn)
    channels = [ChannelSpec(handle="forallqa", category="qa")]
    client = _FakeClient({"forallqa": _HTML.format(channel="forallqa")})

    first = run_fetch(conn, client, channels)
    assert first.leads_inserted == 1
    assert first.channels_processed == 1

    second = run_fetch(conn, client, channels)
    assert second.leads_inserted == 0
    assert second.leads_duplicate == 1


@pytest.mark.db
def test_run_fetch_isolates_channel_error(db_schema):
    conn, _ = db_schema
    _apply_migrations(conn)
    channels = [
        ChannelSpec(handle="broken", category="qa"),
        ChannelSpec(handle="forallqa", category="qa"),
    ]
    client = _FakeClient({
        "broken": RuntimeError("boom"),
        "forallqa": _HTML.format(channel="forallqa"),
    })

    summary = run_fetch(conn, client, channels)
    assert summary.channels_error == 1
    assert summary.channels_processed == 1
    assert summary.leads_inserted == 1
    with conn.cursor() as cur:
        cur.execute("select last_status from source_fetch_state where source_key = %s",
                    ("telegram:broken",))
        assert cur.fetchone()[0] == "error"


@pytest.mark.db
def test_run_fetch_marks_not_found_on_missing_channel(db_schema):
    conn, _ = db_schema
    _apply_migrations(conn)
    channels = [ChannelSpec(handle="gone", category="qa")]
    client = _FakeClient({"gone": None})

    summary = run_fetch(conn, client, channels)
    assert summary.channels_not_found == 1
    with conn.cursor() as cur:
        cur.execute("select last_status from source_fetch_state where source_key = %s",
                    ("telegram:gone",))
        assert cur.fetchone()[0] == "not_found"


@pytest.mark.db
def test_run_fetch_skips_channel_marked_not_found_without_fetching(db_schema):
    conn, _ = db_schema
    _apply_migrations(conn)
    channels = [ChannelSpec(handle="gone", category="qa")]
    client = _FakeClient({"gone": None})
    run_fetch(conn, client, channels)  # first pass marks it not_found

    client2 = _FakeClient({"gone": "should not be called"})
    summary = run_fetch(conn, client2, channels)
    assert summary.channels_skipped == 1
    assert client2.calls == []


_MULTI_HTML = (
    '<div class="tgme_widget_message" data-post="forallqa/1">'
    '<div class="tgme_widget_message_text js-message_text">First</div>'
    '<time datetime="2026-07-15T10:00:00+00:00"></time>'
    '</div>'
    '<div class="tgme_widget_message" data-post="forallqa/2">'
    '<div class="tgme_widget_message_text js-message_text">Second</div>'
    '<time datetime="2026-07-15T10:01:00+00:00"></time>'
    '</div>'
)


@pytest.mark.db
def test_run_fetch_rolls_back_all_messages_on_mid_channel_failure(db_schema, monkeypatch):
    conn, _ = db_schema
    _apply_migrations(conn)
    channels = [ChannelSpec(handle="forallqa", category="qa")]
    client = _FakeClient({"forallqa": _MULTI_HTML})

    from job_machine.telegram_sourcing import service as service_module
    real_upsert = service_module.store.upsert_lead
    calls = {"n": 0}

    def _flaky_upsert(conn, msg):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("boom on second message")
        return real_upsert(conn, msg)

    monkeypatch.setattr(service_module.store, "upsert_lead", _flaky_upsert)

    summary = run_fetch(conn, client, channels)
    assert summary.channels_error == 1
    assert summary.leads_inserted == 0
    with conn.cursor() as cur:
        cur.execute("select count(*) from telegram_lead")
        assert cur.fetchone()[0] == 0
