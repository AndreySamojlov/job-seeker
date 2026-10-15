import pytest

from job_machine.db import migrate
from job_machine.package import service, store
from job_machine.package.models import AnswerRecord
from tests.package.test_store import _seed_application


def _apply(conn):
    for m in migrate.pending(migrate.discover_migrations("db/migrations"),
                             migrate.applied_migrations(conn)):
        migrate.apply_migration(conn, m)


def test_run_package_build_forwards_candidate_id_to_store(monkeypatch):
    """Сервис прокидывает candidate_id в выборку очереди (проброс, без БД)."""
    captured = {}

    def fake_pull(conn, limit=10, candidate_id=None):
        captured["candidate_id"] = candidate_id
        return []

    monkeypatch.setattr(service.store, "pull_needs_package", fake_pull)
    built = service.run_package_build(object(), base_dir="x", limit=5,
                                      candidate_id="daria-b")
    assert built == 0
    assert captured["candidate_id"] == "daria-b"


@pytest.mark.db
def test_run_package_build_end_to_end(db_schema, tmp_path):
    conn, _ = db_schema
    _apply(conn)
    # Резюме поставляет _seed_application (ставит application.resume_artifact_id) — RG-10.
    store.upsert_answers(conn, [
        AnswerRecord(field="English", value="B2", state="locked"),
        AnswerRecord(field="Salary", value="Not locked", state="blocked", rule="ask"),
    ], candidate_id="andrey-s")
    aid = _seed_application(conn, blocker=None, company="Acme")
    _seed_application(conn, blocker="missing_fact", company="Blocked")  # не собирается
    conn.commit()

    built = service.run_package_build(conn, base_dir=str(tmp_path / "applications"), limit=10)
    assert built == 1
    with conn.cursor() as cur:
        cur.execute("select state, payload_hash from application where application_id=%s", (aid,))
        st, ph = cur.fetchone()
        assert st == "package_ready" and len(ph) == 64
        cur.execute("select count(*) from application where state='package_ready'")
        assert cur.fetchone()[0] == 1  # blocked не тронут


@pytest.mark.db
def test_run_package_build_uses_per_candidate_answers(db_schema, tmp_path):
    """Заявки needs_package могут принадлежать разным кандидатам — answer-vault скоуплен,
    поэтому пакет заявки кандидата B должен использовать answers кандидата B, а не A."""
    conn, _ = db_schema
    _apply(conn)
    with conn.cursor() as cur:
        cur.execute("insert into candidate (candidate_id, name) values ('tester-b','B')")
    store.upsert_answers(conn, [
        AnswerRecord(field="English", value="B2 (Andrey)", state="locked"),
    ], candidate_id="andrey-s")
    store.upsert_answers(conn, [
        AnswerRecord(field="English", value="C1 (B)", state="locked"),
    ], candidate_id="tester-b")
    aid_a = _seed_application(conn, blocker=None, company="AcmeA", candidate_id="andrey-s")
    aid_b = _seed_application(conn, blocker=None, company="AcmeB", candidate_id="tester-b")
    conn.commit()

    built = service.run_package_build(conn, base_dir=str(tmp_path / "applications"), limit=10)
    assert built == 2

    with conn.cursor() as cur:
        cur.execute("select payload_json from event where entity_id=%s "
                    "and event_type='application.package_ready'", (aid_a,))
        payload_a = cur.fetchone()[0]
        cur.execute("select payload_json from event where entity_id=%s "
                    "and event_type='application.package_ready'", (aid_b,))
        payload_b = cur.fetchone()[0]
    # disclosed-значения не в событии — сверяем через артефакт манифеста
    manifest_path_a = payload_a["artifacts"]["manifest"]
    manifest_path_b = payload_b["artifacts"]["manifest"]
    import json
    with open(manifest_path_a, encoding="utf-8") as fh:
        manifest_a = json.load(fh)
    with open(manifest_path_b, encoding="utf-8") as fh:
        manifest_b = json.load(fh)
    answers_a = {a["field"]: a["value"] for a in manifest_a["answers"]}
    answers_b = {a["field"]: a["value"] for a in manifest_b["answers"]}
    assert answers_a["English"] == "B2 (Andrey)"
    assert answers_b["English"] == "C1 (B)"
