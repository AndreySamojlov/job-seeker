import pytest

from job_machine.db import migrate


def _apply_migrations(conn):
    for m in migrate.pending(migrate.discover_migrations("db/migrations"),
                             migrate.applied_migrations(conn)):
        migrate.apply_migration(conn, m)


@pytest.mark.db
def test_telegram_lead_table_exists_with_unique_constraint(db_schema):
    conn, _ = db_schema
    _apply_migrations(conn)
    with conn.cursor() as cur:
        cur.execute(
            "insert into telegram_lead (channel, message_id, permalink, raw_text) "
            "values ('forallqa', 1, 'https://t.me/forallqa/1', 'QA Engineer remote')"
        )
        # on conflict — same path the real upsert_lead (a later task) will use; without
        # it the second insert would raise IntegrityError instead of a clean dedup check.
        cur.execute(
            "insert into telegram_lead (channel, message_id, permalink, raw_text) "
            "values ('forallqa', 1, 'https://t.me/forallqa/1', 'dup') "
            "on conflict (channel, message_id) do nothing"
        )
    with conn.cursor() as cur:
        cur.execute("select count(*) from telegram_lead")
        assert cur.fetchone()[0] == 1  # unique(channel, message_id) — 2nd row didn't land


@pytest.mark.db
def test_telegram_lead_triage_table_scoped_by_candidate(db_schema):
    conn, _ = db_schema
    _apply_migrations(conn)
    with conn.cursor() as cur:
        cur.execute(
            "insert into candidate (candidate_id, name) values ('andrey-s', 'Andrey') "
            "on conflict (candidate_id) do nothing")
        cur.execute(
            "insert into candidate (candidate_id, name) values ('daria-b', 'Daria') "
            "on conflict (candidate_id) do nothing")
        cur.execute(
            "insert into telegram_lead (channel, message_id, permalink, raw_text) "
            "values ('forallqa', 1, 'https://t.me/forallqa/1', 'QA Engineer remote') "
            "returning lead_id")
        lead_id = cur.fetchone()[0]
        cur.execute(
            "insert into telegram_lead_triage (lead_id, candidate_id, is_relevant) "
            "values (%s, 'andrey-s', false)", (lead_id,))
        cur.execute(
            "insert into telegram_lead_triage (lead_id, candidate_id, is_relevant) "
            "values (%s, 'daria-b', true)", (lead_id,))
        cur.execute(
            "select candidate_id, is_relevant from telegram_lead_triage "
            "where lead_id = %s order by candidate_id", (lead_id,))
        assert cur.fetchall() == [("andrey-s", False), ("daria-b", True)]


@pytest.mark.db
def test_telegram_lead_drops_legacy_verdict_columns(db_schema):
    conn, schema = db_schema
    _apply_migrations(conn)
    with conn.cursor() as cur:
        cur.execute(
            "select column_name from information_schema.columns "
            "where table_schema = %s and table_name = 'telegram_lead'", (schema,))
        columns = {row[0] for row in cur.fetchall()}
    assert columns == {
        "lead_id", "channel", "message_id", "permalink", "posted_at",
        "raw_text", "fetched_at", "keyword_match",
    }
