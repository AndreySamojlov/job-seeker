import pytest

from job_machine.db import migrate


def _apply(conn):
    for m in migrate.pending(migrate.discover_migrations("db/migrations"),
                             migrate.applied_migrations(conn)):
        migrate.apply_migration(conn, m)


@pytest.mark.db
def test_0012_creates_ledger_tables(db_schema):
    conn, _ = db_schema
    _apply(conn)
    with conn.cursor() as cur:
        cur.execute("select column_name from information_schema.columns "
                    "where table_name='notification_dispatch' order by column_name")
        cols = {r[0] for r in cur.fetchall()}
        assert {"event_id", "kind", "status", "chat_id",
                "tg_message_id", "sent_at"} <= cols
        cur.execute("select column_name from information_schema.columns "
                    "where table_name='notification_daily' order by column_name")
        dcols = {r[0] for r in cur.fetchall()}
        assert {"summary_date", "chat_id", "tg_message_id", "sent_at"} <= dcols
