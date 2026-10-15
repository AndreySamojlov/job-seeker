"""Schema-only contract; agent application logic is a separate integration slice."""
import pytest
from job_machine.db import migrate

pytestmark = pytest.mark.db

@pytest.mark.parametrize('upgrade', [False, True])
def test_recovery_clean_and_baseline_upgrade(db_schema, upgrade):
    conn, schema = db_schema
    migrations = migrate.discover_migrations('db/migrations')
    migrate.applied_migrations(conn)
    if upgrade:
        for item in migrations:
            if item[0] not in {31,34,35}: migrate.apply_migration(conn,item)
    else:
        # A synthetic pre-existing row must survive both migration routes.
        for item in migrations:
            if item[0] <= 30: migrate.apply_migration(conn,item)
    with conn.cursor() as cur:
        cur.execute("insert into candidate(candidate_id,name,headline) values ('synthetic-recovery','Synthetic Candidate','QA')")
        cur.execute("insert into vacancy(company,title,vacancy_status,state) values ('Synthetic recovery','QA','triaged','triaged') returning vacancy_id")
        vacancy=cur.fetchone()[0]
        cur.execute("insert into application(vacancy_id,candidate_id,verdict,state) values (%s,'synthetic-recovery','apply','needs_package') returning application_id",(vacancy,))
        application=cur.fetchone()[0]
    conn.commit()
    for item in migrate.pending(migrations,migrate.applied_migrations(conn)):
        migrate.apply_migration(conn,item)
    with conn.cursor() as cur:
        cur.execute("select column_name from information_schema.columns where table_schema=%s and table_name='application'",(schema,))
        assert {'agent_fill_session_id','agent_fill_started_at'} <= {r[0] for r in cur.fetchall()}
        cur.execute("select state, agent_fill_session_id from application where application_id=%s",(application,))
        assert cur.fetchone() == ('needs_package',None)
        cur.execute("update application set state='agent_fill_pending' where application_id=%s",(application,))
        cur.execute("select core_role_families from search_profile limit 0")
        cur.execute("select skip_category from triage_result limit 0")
    conn.commit()
    assert not migrate.pending(migrations,migrate.applied_migrations(conn))
