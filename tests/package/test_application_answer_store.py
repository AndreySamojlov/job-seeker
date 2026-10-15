import pytest
from job_machine.db import migrate
from job_machine.package import store
from job_machine.package.models import AnswerRecord


def _apply(conn):
    for m in migrate.pending(migrate.discover_migrations("db/migrations"),
                             migrate.applied_migrations(conn)):
        migrate.apply_migration(conn, m)


def _seed_app(conn):
    with conn.cursor() as cur:
        cur.execute("insert into vacancy (company,title,canonical_url,state) "
                    "values ('Acme','QA','https://a/1','triaged') returning vacancy_id")
        vid = cur.fetchone()[0]
        cur.execute("insert into application (vacancy_id,candidate_id,state) "
                    "values (%s,'andrey-s','needs_package') "
                    "returning application_id", (vid,))
        return str(cur.fetchone()[0])


@pytest.mark.db
def test_upsert_and_load_application_answers(db_schema):
    conn, _ = db_schema
    _apply(conn)
    aid = _seed_app(conn)
    store.upsert_application_answers(conn, aid, [
        AnswerRecord(field="Preferred location", value="Remote, Germany", state="locked"),
        AnswerRecord(field="How did you hear about this role?", value="Job Board", state="locked"),
    ])
    conn.commit()
    store.upsert_application_answers(conn, aid, [
        AnswerRecord(field="Preferred location", value="Berlin", state="locked")])
    conn.commit()
    out = store.load_application_answers(conn, aid)
    by = {a.field: a.value for a in out}
    assert by["Preferred location"] == "Berlin"
    assert by["How did you hear about this role?"] == "Job Board"
    assert len(out) == 2
