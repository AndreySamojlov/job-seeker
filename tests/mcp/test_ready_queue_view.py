import pytest

from job_machine.db import migrate


def _apply(conn):
    for m in migrate.pending(migrate.discover_migrations("db/migrations"),
                             migrate.applied_migrations(conn)):
        migrate.apply_migration(conn, m)


def _seed_pre_submit_ready(conn):
    with conn.cursor() as cur:
        cur.execute("insert into vacancy (company, title, canonical_url, ats_family, "
                    "vacancy_status, state) values ('Acme','QA Lead',"
                    "'https://acme/apply','greenhouse','triaged','triaged') "
                    "returning vacancy_id")
        vid = cur.fetchone()[0]
        cur.execute("insert into application (vacancy_id, candidate_id, state, "
                    "current_blocker, payload_hash) "
                    "values (%s,'andrey-s','pre_submit_ready',null,'ph1') "
                    "returning application_id", (vid,))
        aid = cur.fetchone()[0]
        cur.execute("insert into event (entity_type, entity_id, event_type, payload_json) "
                    "values ('application', %s, 'application.pre_submit_ready', "
                    "'{\"screenshot_path\": \"/art/shot.png\"}'::jsonb)", (aid,))
    return str(aid)


@pytest.mark.db
def test_ready_queue_lists_pre_submit_ready_with_screenshot(db_schema):
    conn, _ = db_schema
    _apply(conn)
    aid = _seed_pre_submit_ready(conn)
    conn.commit()
    with conn.cursor() as cur:
        cur.execute("select application_id, company, role, url, status, "
                    "payload_hash, screenshot_path from ready_queue")
        rows = cur.fetchall()
    assert len(rows) == 1
    r = rows[0]
    assert str(r[0]) == aid
    assert r[1] == "Acme" and r[2] == "QA Lead"
    assert r[3] == "https://acme/apply"
    assert r[4] == "pre_submit_ready"
    assert r[5] == "ph1"
    assert r[6] == "/art/shot.png"
