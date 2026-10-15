import uuid

import pytest

from job_machine import provenance
from job_machine.db import migrate
from job_machine.package import store as pkg_store
from job_machine.package.builder import build_package
from job_machine.package.models import (
    AnswerRecord, PackageInput, ResumeArtifact,
)


def _apply(conn):
    for m in migrate.pending(migrate.discover_migrations("db/migrations"),
                             migrate.applied_migrations(conn)):
        migrate.apply_migration(conn, m)


def _seed_application(conn):
    """Вакансия + application в needs_package; вернуть application_id (str)."""
    key = uuid.uuid4().hex[:8]
    with conn.cursor() as cur:
        cur.execute(
            "insert into vacancy (source, source_url, canonical_url, title, "
            "vacancy_status, state) values "
            "('greenhouse', %s, %s, 'EM', 'triaged', 'triaged') returning vacancy_id",
            (f"https://api/jobs/{key}", f"https://x/{key}"))
        vid = cur.fetchone()[0]
        cur.execute(
            "insert into application (vacancy_id, candidate_id, verdict, package_status, state) "
            "values (%s,'andrey-s','apply','none','needs_package') returning application_id",
            (vid,))
        return str(cur.fetchone()[0])


# --- §3 guard: версия НЕ влияет на payload_hash ---

def test_answers_version_differs_but_payload_hash_stable():
    """Правка blocked-answer (не disclosed) меняет answers_version, но НЕ payload_hash."""
    base_answers = [
        AnswerRecord(field="English", value="B2", state="locked"),
        AnswerRecord(field="Work authorization", value="Unknown", state="blocked",
                     rule="Never claim authorized"),
    ]
    mutated_answers = [
        AnswerRecord(field="English", value="B2", state="locked"),
        AnswerRecord(field="Work authorization", value="Unknown", state="blocked",
                     rule="DIFFERENT RULE"),
    ]
    inp = PackageInput(application_id="a1", company="Acme", role="QA Lead",
                       destination_url="https://acme/apply")
    resume = ResumeArtifact(filename="r.pdf", path="/x/r.pdf", content_hash="rh")
    base_hash = build_package(inp, base_answers, resume).payload_hash
    mut_hash = build_package(inp, mutated_answers, resume).payload_hash
    assert base_hash == mut_hash  # disclosed-набор не изменился → payload_hash стабилен
    assert provenance.answers_version(base_answers) != provenance.answers_version(mutated_answers)


@pytest.mark.db
def test_record_package_writes_answers_version(db_schema):
    conn, _ = db_schema
    _apply(conn)
    aid = _seed_application(conn)
    conn.commit()
    answers = [AnswerRecord(field="English", value="B2", state="locked")]
    inp = PackageInput(application_id=aid, company="Acme", role="QA Lead",
                       destination_url="https://acme/apply")
    resume = ResumeArtifact(filename="r.pdf", path="/x/r.pdf", content_hash="rh")
    manifest = build_package(inp, answers, resume)
    av = provenance.answers_version(answers)
    pkg_store.record_package(conn, manifest, [], answers_version=av)
    conn.commit()
    with conn.cursor() as cur:
        cur.execute("select answers_version from application where application_id=%s",
                    (uuid.UUID(aid),))
        assert cur.fetchone()[0] == av
