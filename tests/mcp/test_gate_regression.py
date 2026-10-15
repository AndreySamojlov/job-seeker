import pytest

from job_machine.db import migrate
from job_machine.mcp import tools


def _apply(conn):
    for m in migrate.pending(migrate.discover_migrations("db/migrations"),
                             migrate.applied_migrations(conn)):
        migrate.apply_migration(conn, m)


class FakeBrowser:
    def create_session(self): return "sid"
    def inspect(self, sid, url): raise AssertionError("inspect must not be called")
    def submit(self, sid, fields, resume_path=None):
        raise AssertionError("submit must not be reached without approval")
    def dispose(self, sid): pass


class LocalWorker:
    """In-process стенд job-submit воркера: submit_one зовёт НАСТОЯЩИЙ run_submit_one
    против реального conn+browser. Покрытие gate (§3) идентично прежнему — меняется лишь
    шов делегирования (HTTP-граница отдельно покрыта test_submit_worker_client/test_app)."""
    def __init__(self, conn, browser):
        self._conn, self._browser = conn, browser

    def submit_one(self, application_id):
        from job_machine.submit import service
        return service.run_submit_one(self._conn, self._browser, application_id)


@pytest.mark.db
def test_submit_without_approval_is_blocked_not_submitted(db_schema):
    conn, _ = db_schema
    _apply(conn)
    with conn.cursor() as cur:
        cur.execute("insert into vacancy (company, title, canonical_url, state) "
                    "values ('Acme','QA','https://acme/apply','triaged') "
                    "returning vacancy_id")
        vid = cur.fetchone()[0]
        cur.execute("insert into application (vacancy_id, candidate_id, state, payload_hash) "
                    "values (%s,'andrey-s','pre_submit_ready','ph1') returning application_id",
                    (vid,))
        aid = str(cur.fetchone()[0])
    conn.commit()

    out = tools.submit_application(conn, LocalWorker(conn, FakeBrowser()), aid)
    assert out["submitted"] == 0
    with conn.cursor() as cur:
        cur.execute("select state from application where application_id=%s", (aid,))
        assert cur.fetchone()[0] != "submitted"
