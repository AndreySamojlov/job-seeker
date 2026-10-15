import pytest

from job_machine.db import migrate
from job_machine.resume import store


def _apply(conn):
    for m in migrate.pending(migrate.discover_migrations("db/migrations"),
                             migrate.applied_migrations(conn)):
        migrate.apply_migration(conn, m)


@pytest.mark.db
def test_load_contact_present_and_absent(db_schema):
    conn, _ = db_schema
    _apply(conn)
    # Реальные ключи answer-vault (Task 0): 'Email', 'Phone', 'Current location'.
    # LinkedIn в vault нет → всегда None (§3: не выдумываем).
    with conn.cursor() as cur:
        cur.execute(
            "insert into answer (candidate_id, field, value, state) values "
            "('andrey-s','Email','a@b.com','locked'),"
            "('andrey-s','Current location','Moscow, Russia','locked') "
            "on conflict do nothing")
    conn.commit()
    c = store.load_contact(conn, "andrey-s")
    assert c.email == "a@b.com" and c.location == "Moscow, Russia"
    assert c.phone is None and c.linkedin is None   # отсутствующие → None


@pytest.mark.db
def test_load_contact_ignores_other_candidate(db_schema):
    conn, _ = db_schema
    _apply(conn)
    with conn.cursor() as cur:
        cur.execute("insert into candidate (candidate_id, name) values ('other','Other') "
                    "on conflict do nothing")
        cur.execute(
            "insert into answer (candidate_id, field, value, state) values "
            "('other','Email','other@x.com','locked') on conflict do nothing")
    conn.commit()
    c = store.load_contact(conn, "andrey-s")
    assert c.email is None   # не подтягиваем чужие контакты
