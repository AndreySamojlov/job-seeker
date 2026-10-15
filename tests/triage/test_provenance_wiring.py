import uuid

import pytest

from job_machine import provenance
from job_machine.db import migrate
from job_machine.triage import service, store
from job_machine.triage.models import (
    ClaimRecord, HardRequirementMatch, TriageVerdict,
)


def _apply(conn):
    for m in migrate.pending(migrate.discover_migrations("db/migrations"),
                             migrate.applied_migrations(conn)):
        migrate.apply_migration(conn, m)


def _seed_verified(conn, title="Engineering Manager", work_mode="remote"):
    key = uuid.uuid4().hex[:8]
    with conn.cursor() as cur:
        cur.execute(
            "insert into vacancy (source, source_url, canonical_url, title, "
            "work_mode, vacancy_status, state, verified_at) values "
            "('greenhouse', %s, %s, %s, %s, 'verified', 'verified', now()) "
            "returning vacancy_id",
            (f"https://api/jobs/{key}", f"https://x/{key}", title, work_mode))
        return str(cur.fetchone()[0])


class FakeClient:
    def fetch_content(self, api_url):
        return "<p>role content</p>"


@pytest.mark.db
def test_build_inputs_sets_claims_version(db_schema):
    conn, _ = db_schema
    _apply(conn)
    _seed_verified(conn)
    claims = [ClaimRecord(claim_id="C-001", claim_text="x", status="verified")]
    store.upsert_claims(conn, claims, candidate_id="andrey-s")
    conn.commit()
    summary = service.build_triage_inputs(conn, FakeClient(), candidate_id="andrey-s", limit=10)
    assert summary.claims_version == provenance.claims_version(claims)


@pytest.mark.db
def test_apply_verdict_writes_claims_version_to_application(db_schema):
    conn, _ = db_schema
    _apply(conn)
    vid = _seed_verified(conn)
    conn.commit()
    verdict = TriageVerdict(
        vacancy_id=vid, verdict="apply", fit_summary="ok",
        hard_requirements=[HardRequirementMatch(requirement="r", status="strong")])
    store.apply_verdict(conn, verdict, candidate_id="andrey-s", claims_version="cv-xyz")
    conn.commit()
    with conn.cursor() as cur:
        cur.execute("select claims_version from application where vacancy_id=%s",
                    (uuid.UUID(vid),))
        assert cur.fetchone()[0] == "cv-xyz"


@pytest.mark.db
def test_apply_verdict_claims_version_defaults_none(db_schema):
    conn, _ = db_schema
    _apply(conn)
    vid = _seed_verified(conn)
    conn.commit()
    verdict = TriageVerdict(
        vacancy_id=vid, verdict="apply", fit_summary="ok",
        hard_requirements=[HardRequirementMatch(requirement="r", status="strong")])
    store.apply_verdict(conn, verdict, candidate_id="andrey-s")  # без claims_version → NULL
    conn.commit()
    with conn.cursor() as cur:
        cur.execute("select claims_version from application where vacancy_id=%s",
                    (uuid.UUID(vid),))
        assert cur.fetchone()[0] is None
