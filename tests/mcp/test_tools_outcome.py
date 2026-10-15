import pytest

from job_machine.db import migrate
from job_machine.mcp import store, tools


class FakeConn:
    def close(self): pass


VALID_ID = "1b4e28ba-2fa1-11d2-883f-0016d3cca427"


def test_record_outcome_rejects_invalid_uuid(tmp_path):
    out = tools.record_outcome(FakeConn(), "not-a-uuid",
                               csv_path=str(tmp_path / "s.csv"))
    assert out["recorded"] is False
    assert "invalid" in out["error"]
    assert not (tmp_path / "s.csv").exists()


def test_record_outcome_unknown_id_fails_closed(monkeypatch, tmp_path):
    monkeypatch.setattr(tools.funnel, "sync_submissions",
                        lambda conn, path, application_id=None:
                        {"appended": 0, "skipped": 0, "matched": 0, "invalid": [], "application_ids": []})
    out = tools.record_outcome(FakeConn(), VALID_ID, csv_path=str(tmp_path / "s.csv"))
    assert out["recorded"] is False
    assert "no application.submitted" in out["error"]


def test_record_outcome_appends_from_db(monkeypatch, tmp_path):
    calls = []
    def _sync(conn, path, application_id=None):
        calls.append(application_id)
        return {"appended": 1, "skipped": 0, "matched": 1, "invalid": [], "application_ids": [application_id]}
    monkeypatch.setattr(tools.funnel, "sync_submissions", _sync)
    out = tools.record_outcome(FakeConn(), VALID_ID, csv_path=str(tmp_path / "s.csv"))
    assert out["recorded"] is True
    assert out["already_recorded"] is False
    assert calls == [VALID_ID]


def test_record_outcome_idempotent_when_already_in_csv(monkeypatch, tmp_path):
    monkeypatch.setattr(tools.funnel, "sync_submissions",
                        lambda conn, path, application_id=None:
                        {"appended": 0, "skipped": 1, "matched": 1, "invalid": [], "application_ids": []})
    out = tools.record_outcome(FakeConn(), VALID_ID, csv_path=str(tmp_path / "s.csv"))
    assert out["recorded"] is True
    assert out["already_recorded"] is True


def _apply(conn):
    for m in migrate.pending(migrate.discover_migrations("db/migrations"),
                             migrate.applied_migrations(conn)):
        migrate.apply_migration(conn, m)


@pytest.mark.db
def test_funnel_stats_counts_by_state(db_schema):
    conn, _ = db_schema
    _apply(conn)
    with conn.cursor() as cur:
        cur.execute("insert into vacancy (company, title, canonical_url, state) "
                    "values ('A','R','u','triaged') returning vacancy_id")
        vid = cur.fetchone()[0]
        cur.execute("insert into application (vacancy_id, candidate_id, state) values "
                    "(%s,'andrey-s','pre_submit_ready'),(%s,'andrey-s','submitted'),"
                    "(%s,'andrey-s','submitted')",
                    (vid, vid, vid))
    conn.commit()
    stats = store.count_by_state(conn, candidate_id="andrey-s")
    assert stats.get("submitted") == 2
    assert stats.get("pre_submit_ready") == 1
