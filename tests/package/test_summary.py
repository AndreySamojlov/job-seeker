# tests/package/test_summary.py
from job_machine.package.builder import build_package
from job_machine.package.models import AnswerRecord, PackageInput, ResumeArtifact
from job_machine.package.summary import render_summary

VAULT = [
    AnswerRecord(field="English", value="B2", state="locked"),
    AnswerRecord(field="Work authorization", value="Unknown", state="blocked",
                 rule="Never claim authorized"),
    AnswerRecord(field="Talent pool", value="No by default", state="optional-policy"),
]
RESUME = ResumeArtifact(filename="Andrey_QA.pdf", path="/x/Andrey_QA.pdf", content_hash="rh123")
INP = PackageInput(application_id="a1", company="Acme", role="QA Lead",
                   destination_url="https://acme/apply", fit_summary="strong QA match")


def test_summary_contains_all_disclosure_fields():
    m = build_package(INP, VAULT, RESUME)
    text = render_summary(m)
    assert "Acme" in text and "QA Lead" in text
    assert "https://acme/apply" in text
    assert "Andrey_QA.pdf" in text and "rh123" in text
    assert "English" in text and "B2" in text          # disclosed answer
    assert "Talent pool" in text                        # consent
    assert "Work authorization" in text                 # warning раскрыт
    assert m.payload_hash in text                       # binding hash виден
    # сводка — на русском (есть кириллические заголовки)
    assert "Резюме" in text or "Ответы" in text


def test_summary_discloses_caveats_for_owner_approval():
    """§3 disclosed-caveats: гэпы под требования роли ВИДНЫ владельцу при одобрении."""
    inp = PackageInput(application_id="a1", company="Acme", role="EM",
                       destination_url="https://acme/apply", fit_summary="good with gaps",
                       material_unknowns=["Commercial Linux experience",
                                          "Hands-on AI/ML product delivery"],
                       overclaim_risks=["needs visa sponsorship"])
    text = render_summary(build_package(inp, VAULT, RESUME))
    assert "Честные оговорки" in text
    assert "Commercial Linux experience" in text
    assert "Hands-on AI/ML product delivery" in text
    assert "needs visa sponsorship" in text


def test_summary_omits_caveats_section_when_none():
    text = render_summary(build_package(INP, VAULT, RESUME))   # INP без оговорок
    assert "Честные оговорки" not in text
