import pytest
from job_machine.db import migrate


def _apply(conn):
    for m in migrate.pending(migrate.discover_migrations("db/migrations"),
                             migrate.applied_migrations(conn)):
        migrate.apply_migration(conn, m)


@pytest.mark.db
def test_application_answer_table_roundtrip(db_schema):
    conn, _ = db_schema
    _apply(conn)
    with conn.cursor() as cur:
        cur.execute("insert into vacancy (company,title,canonical_url,state) "
                    "values ('Acme','QA','https://a/1','triaged') returning vacancy_id")
        vid = cur.fetchone()[0]
        cur.execute("insert into application (vacancy_id,candidate_id,state) "
                    "values (%s,'andrey-s','needs_package') "
                    "returning application_id", (vid,))
        aid = cur.fetchone()[0]
        cur.execute("insert into application_answer (application_id,field,value,state) "
                    "values (%s,'Preferred location','Remote, Germany','locked')", (aid,))
        cur.execute("insert into application_answer (application_id,field,value,state) "
                    "values (%s,'Preferred location','Berlin','locked') "
                    "on conflict (application_id,field) do update set value=excluded.value", (aid,))
        cur.execute("select value from application_answer where application_id=%s", (aid,))
        rows = cur.fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "Berlin"
