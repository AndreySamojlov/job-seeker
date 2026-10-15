from job_machine.package.models import (
    AnswerRecord, DisclosedAnswer, DisclosedConsent, UnresolvedFact,
    PackageInput, ResumeArtifact, PackageManifest,
)


def test_answer_record_states():
    a = AnswerRecord(field="English", value="B2", state="locked", rule="Never upgrade")
    assert a.state == "locked"


def test_manifest_roundtrip():
    resume = ResumeArtifact(filename="cv.pdf", path="/x/cv.pdf", content_hash="abc")
    m = PackageManifest(
        application_id="11111111-1111-1111-1111-111111111111",
        company="Acme", role="QA Lead", destination_url="https://acme/apply",
        resume=resume,
        answers=[DisclosedAnswer(field="English", value="B2", source="locked")],
        consents=[DisclosedConsent(field="Talent pool", decision="No", source="policy")],
        warnings=[UnresolvedFact(field="Work authorization", rule="Never claim")],
        fit_summary="strong", hard_requirements=[{"requirement": "QA", "status": "strong"}],
        answers_hash="h1", consents_hash="h2", payload_hash="h3",
    )
    assert m.resume.content_hash == "abc"
    assert m.answers[0].source == "locked"
    assert m.model_dump()["payload_hash"] == "h3"
