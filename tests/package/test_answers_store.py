import pytest

from job_machine.db import migrate
from job_machine.package import store
from job_machine.package.models import AnswerRecord


def _apply(conn):
    for m in migrate.pending(migrate.discover_migrations("db/migrations"),
                             migrate.applied_migrations(conn)):
        migrate.apply_migration(conn, m)


@pytest.mark.db
def test_upsert_and_load_answers(db_schema):
    conn, _ = db_schema
    _apply(conn)
    store.upsert_answers(conn, [
        AnswerRecord(field="English", value="B2", state="locked", rule="no upgrade"),
        AnswerRecord(field="Salary", value="Not locked", state="blocked", rule="ask"),
    ], candidate_id="andrey-s")
    conn.commit()
    # upsert повторно меняет value
    store.upsert_answers(conn, [
        AnswerRecord(field="English", value="B2 upper", state="locked", rule="no upgrade"),
    ], candidate_id="andrey-s")
    conn.commit()
    loaded = {a.field: a for a in store.load_answers(conn, candidate_id="andrey-s")}
    assert loaded["English"].value == "B2 upper"
    assert loaded["Salary"].state == "blocked"
    assert len(loaded) == 2


@pytest.mark.db
def test_answers_scoped_by_candidate(db_schema):
    conn, _ = db_schema
    _apply(conn)
    with conn.cursor() as cur:
        cur.execute("insert into candidate (candidate_id, name) values ('tester-b','B')")
    store.upsert_answers(conn, [AnswerRecord(field="English", value="B2", state="locked", rule="")],
                         candidate_id="tester-b")
    conn.commit()
    assert len(store.load_answers(conn, candidate_id="tester-b")) == 1
    assert store.load_answers(conn, candidate_id="andrey-s") == []
