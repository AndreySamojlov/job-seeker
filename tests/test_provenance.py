from job_machine import provenance
from job_machine.triage.models import ClaimRecord
from job_machine.package.models import AnswerRecord


def _claims():
    return [
        ClaimRecord(claim_id="C-001", claim_text="13+ yrs", status="verified",
                    safe_use="Resume"),
        ClaimRecord(claim_id="C-014", claim_text="no commercial coding",
                    status="verified", safe_use="Never claim hands-on"),
    ]


def _answers():
    return [
        AnswerRecord(field="English", value="B2", state="locked"),
        AnswerRecord(field="Work authorization", value="Unknown", state="blocked",
                     rule="Never claim authorized"),
    ]


def test_claims_version_deterministic():
    assert provenance.claims_version(_claims()) == provenance.claims_version(_claims())


def test_claims_version_order_independent():
    a = _claims()
    b = list(reversed(_claims()))
    assert provenance.claims_version(a) == provenance.claims_version(b)


def test_claims_version_sensitive_to_field_change():
    base = provenance.claims_version(_claims())
    mutated = _claims()
    mutated[0].status = "approximate"
    assert provenance.claims_version(mutated) != base


def test_answers_version_deterministic_and_sensitive():
    base = provenance.answers_version(_answers())
    assert base == provenance.answers_version(_answers())
    mutated = _answers()
    mutated[1].rule = "changed rule"
    assert provenance.answers_version(mutated) != base


def test_empty_snapshot_is_stable_hash():
    assert provenance.claims_version([]) == provenance.claims_version([])
    assert provenance.answers_version([]) == provenance.answers_version([])
    assert isinstance(provenance.claims_version([]), str)
