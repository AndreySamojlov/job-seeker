import pytest

from job_machine.db import migrate


def _apply(conn):
    for m in migrate.pending(migrate.discover_migrations("db/migrations"),
                             migrate.applied_migrations(conn)):
        migrate.apply_migration(conn, m)


@pytest.mark.db
def test_candidate_scoping_columns_and_backfill(db_schema):
    conn, _ = db_schema
    _apply(conn)
    with conn.cursor() as cur:
        cur.execute("select name, headline from candidate where candidate_id='andrey-s'")
        assert cur.fetchone() == ("Andrey Samoylov", "IT Delivery / QA Leader")
        for table in ("application", "event", "search_profile",
                      "claim", "answer", "cloud_position",
                      "cloud_achievement", "cloud_skill", "triage_result"):
            cur.execute(
                "select 1 from information_schema.columns "
                "where table_name=%s and column_name='candidate_id' "
                "and table_schema=current_schema()", (table,))
            assert cur.fetchone() is not None, f"{table} missing candidate_id"
        cur.execute("select 1 from information_schema.columns "
                    "where table_name='search_profile' and column_name='profile_key' "
                    "and table_schema=current_schema()")
        assert cur.fetchone() is None, "profile_key should be dropped"


@pytest.mark.db
def test_backfill_and_composite_pk(db_schema):
    conn, _ = db_schema
    migs = migrate.discover_migrations("db/migrations")
    # applied_migrations создаёт schema_migrations, чтобы прямой apply_migration
    # (пишущий в неё) не падал на пустой temp-схеме.
    migrate.applied_migrations(conn)
    # применить 0001–0009 (тем же способом, что _apply, но до номера 10)
    for m in migs:
        if m[0] < 10:
            migrate.apply_migration(conn, m)
    with conn.cursor() as cur:
        cur.execute("insert into vacancy (company, title, vacancy_status, state) "
                    "values ('Co','QA','triaged','triaged') returning vacancy_id")
        vid = cur.fetchone()[0]
        cur.execute("insert into application (vacancy_id, verdict, state) "
                    "values (%s,'apply','needs_package')", (vid,))
        cur.execute("insert into claim (claim_id, claim_text, status) "
                    "values ('C-001','x','verified')")
    migrate.apply_migration(conn, next(m for m in migs if m[0] == 10))
    with conn.cursor() as cur:
        cur.execute("select candidate_id from application where vacancy_id=%s", (vid,))
        assert cur.fetchone()[0] == "andrey-s"
        cur.execute("select candidate_id from claim where claim_id='C-001'")
        assert cur.fetchone()[0] == "andrey-s"
        cur.execute("select verdict from triage_result where candidate_id='andrey-s' and vacancy_id=%s", (vid,))
        assert cur.fetchone()[0] == "apply"
        cur.execute("insert into candidate (candidate_id, name) values ('tester-b','B')")
        cur.execute("insert into claim (candidate_id, claim_id, claim_text, status) "
                    "values ('tester-b','C-001','y','verified')")
        cur.execute("select count(*) from claim where claim_id='C-001'")
        assert cur.fetchone()[0] == 2
