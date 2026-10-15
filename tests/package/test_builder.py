from job_machine.package import hashing
from job_machine.package.builder import build_package
from job_machine.package.models import AnswerRecord, PackageInput, ResumeArtifact

VAULT = [
    AnswerRecord(field="English", value="B2", state="locked", rule="no upgrade"),
    AnswerRecord(field="Notice period", value="1 month", state="locked"),
    AnswerRecord(field="Work authorization", value="Unknown", state="blocked",
                 rule="Never claim authorized"),
    AnswerRecord(field="Salary", value="Not locked", state="blocked", rule="ask"),
    AnswerRecord(field="Talent pool", value="No by default", state="optional-policy"),
]
RESUME = ResumeArtifact(filename="cv.pdf", path="/x/cv.pdf", content_hash="rh")
INP = PackageInput(application_id="a1", company="Acme", role="QA Lead",
                   destination_url="https://acme/apply", fit_summary="strong")


def test_blocked_facts_are_warnings_not_answers():
    m = build_package(INP, VAULT, RESUME)
    answered = {a.field for a in m.answers}
    warned = {w.field for w in m.warnings}
    assert answered == {"English", "Notice period"}
    assert warned == {"Work authorization", "Salary"}
    # blocked-значения НЕ участвуют в payload_hash
    locked_only = [a for a in VAULT if a.state == "locked"]
    from job_machine.package.models import DisclosedAnswer
    expected = hashing.payload_hash(
        INP.destination_url, RESUME.content_hash,
        [DisclosedAnswer(field=a.field, value=a.value) for a in locked_only],
        [c for c in m.consents])
    assert m.payload_hash == expected


def test_optional_policy_becomes_consent():
    m = build_package(INP, VAULT, RESUME)
    assert [c.field for c in m.consents] == ["Talent pool"]
    assert m.consents[0].decision == "No by default"


def test_hashes_present_and_consistent():
    m = build_package(INP, VAULT, RESUME)
    assert m.answers_hash == hashing.answers_hash(m.answers)
    assert m.consents_hash == hashing.consents_hash(m.consents)
    assert len(m.payload_hash) == 64


def test_rebind_destination_recomputes_only_payload_hash():
    from job_machine.package.builder import rebind_destination
    inp = PackageInput(application_id="a1", company="Acme", role="Eng",
                       destination_url="https://boards.greenhouse.io/acme/jobs/1")
    m = build_package(inp, VAULT, RESUME)
    final = "https://job-boards.greenhouse.io/acme/jobs/1"
    m2 = rebind_destination(m, final)
    assert m2.destination_url == final
    assert m2.payload_hash == hashing.payload_hash(
        final, RESUME.content_hash, m.answers, m.consents)
    assert m2.payload_hash != m.payload_hash
    assert (m2.answers_hash, m2.consents_hash) == (m.answers_hash, m.consents_hash)
    assert m.destination_url == "https://boards.greenhouse.io/acme/jobs/1"  # исходный не мутирован


def test_caveats_carried_into_manifest_but_not_into_payload_hash():
    """material_unknowns/overclaim_risks раскрываются, но НЕ влияют на payload_hash
    (это оговорки для одобрения, а не передаваемые ответы)."""
    inp = PackageInput(application_id="a1", company="Acme", role="EM",
                       destination_url="https://acme/apply",
                       material_unknowns=["Commercial Linux experience"],
                       overclaim_risks=["needs visa sponsorship"])
    m = build_package(inp, VAULT, RESUME)
    assert m.material_unknowns == ["Commercial Linux experience"]
    assert m.overclaim_risks == ["needs visa sponsorship"]
    # payload_hash идентичен варианту без оговорок (оговорки не входят в payload)
    assert m.payload_hash == build_package(INP, VAULT, RESUME).payload_hash
