import pytest

from job_machine.db import migrate
from job_machine.triage import store
from job_machine.triage.models import ClaimRecord


def _apply(conn):
    for m in migrate.pending(migrate.discover_migrations("db/migrations"),
                             migrate.applied_migrations(conn)):
        migrate.apply_migration(conn, m)


@pytest.mark.db
def test_upsert_then_load_roundtrips(db_schema):
    conn, _ = db_schema
    _apply(conn)
    claims = [
        ClaimRecord(claim_id="C-001", claim_text="13+ yrs", status="verified",
                    safe_use="Resume"),
        ClaimRecord(claim_id="C-014", claim_text="no commercial coding",
                    status="verified", safe_use="Never claim hands-on"),
    ]
    store.upsert_claims(conn, claims, candidate_id="andrey-s")
    conn.commit()

    loaded = store.load_claims(conn, candidate_id="andrey-s")
    by_id = {c.claim_id: c for c in loaded}
    assert set(by_id) == {"C-001", "C-014"}
    assert by_id["C-014"].safe_use == "Never claim hands-on"


@pytest.mark.db
def test_upsert_is_idempotent_and_updates(db_schema):
    conn, _ = db_schema
    _apply(conn)
    store.upsert_claims(conn, [ClaimRecord(claim_id="C-001", claim_text="old",
                                           status="verified")], candidate_id="andrey-s")
    store.upsert_claims(conn, [ClaimRecord(claim_id="C-001", claim_text="new",
                                           status="approximate")], candidate_id="andrey-s")
    conn.commit()
    loaded = store.load_claims(conn, candidate_id="andrey-s")
    assert len(loaded) == 1
    assert loaded[0].claim_text == "new" and loaded[0].status == "approximate"


@pytest.mark.db
def test_claims_scoped_by_candidate(db_schema):
    conn, _ = db_schema
    _apply(conn)
    with conn.cursor() as cur:
        cur.execute("insert into candidate (candidate_id, name) values ('tester-b','B')")
    store.upsert_claims(conn, [ClaimRecord(claim_id="C-001", claim_text="x", status="verified")],
                        candidate_id="tester-b")
    conn.commit()
    assert [c.claim_id for c in store.load_claims(conn, candidate_id="tester-b")] == ["C-001"]
    assert store.load_claims(conn, candidate_id="andrey-s") == []
