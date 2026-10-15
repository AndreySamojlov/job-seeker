from job_machine.resume import honesty
from job_machine.resume.models import (
    PhrasedBullet, ResumePhrasing, ResumeSelection, SelectedBullet, SelectedPosition,
)


def _sel():
    return ResumeSelection(
        application_id="a1", headline="H",
        positions=[SelectedPosition(pid="P-01", company="NSD", title="Head of QA",
            bullets=[
                SelectedBullet(aid="A-04", source_text="Throughput delivered under management",
                               source_metric="15,000 test-hours; 1,600 defects"),
                SelectedBullet(aid="A-03", source_text="Introduced Scrum improving delivery",
                               source_metric="2.5x"),
            ])])


def test_keeps_phrasing_within_source_numbers():
    phr = ResumePhrasing(application_id="a1", bullets=[
        PhrasedBullet(aid="A-04", phrased_text="Owned delivery of 15,000 test-hours and 1,600 defects")])
    out = honesty.verify(_sel(), phr)
    assert out["A-04"].startswith("Owned delivery of 15,000")   # accepted


def test_rejects_introduced_number_falls_back_to_source():
    phr = ResumePhrasing(application_id="a1", bullets=[
        PhrasedBullet(aid="A-04", phrased_text="Delivered 99,000 test-hours of throughput")])
    out = honesty.verify(_sel(), phr)
    assert out["A-04"] == "Throughput delivered under management"  # verbatim fallback


def test_rejects_forbidden_token():
    phr = ResumePhrasing(application_id="a1", bullets=[
        PhrasedBullet(aid="A-03", phrased_text="Built CI/CD pipeline on Jenkins improving delivery 2.5x")])
    out = honesty.verify(_sel(), phr)
    assert out["A-03"] == "Introduced Scrum improving delivery"   # verbatim fallback


def test_missing_phrasing_uses_source():
    out = honesty.verify(_sel(), ResumePhrasing(application_id="a1", bullets=[]))
    assert out["A-04"] == "Throughput delivered under management"
    assert out["A-03"] == "Introduced Scrum improving delivery"


def test_rejects_introduced_named_tool_falls_back_to_source():
    # Выдуманные инструменты (Capitalized + tech-денилист), которых нет в источнике.
    phr = ResumePhrasing(application_id="a1", bullets=[
        PhrasedBullet(aid="A-04", phrased_text="Owned delivery scaling on Kubernetes and AWS")])
    out = honesty.verify(_sel(), phr)
    assert out["A-04"] == "Throughput delivered under management"  # verbatim fallback


def test_rejects_capitalized_employer_or_platform():
    # "Salesforce" — Capitalized в середине предложения + tech-денилист, нет в источнике.
    phr = ResumePhrasing(application_id="a1", bullets=[
        PhrasedBullet(aid="A-03", phrased_text="Drove company-wide Salesforce adoption 2.5x")])
    out = honesty.verify(_sel(), phr)
    assert out["A-03"] == "Introduced Scrum improving delivery"   # verbatim fallback


def test_allows_capitalized_word_present_in_source():
    # "Scrum" с заглавной, НО оно есть в source_text → не считается выдумкой.
    phr = ResumePhrasing(application_id="a1", bullets=[
        PhrasedBullet(aid="A-03", phrased_text="Rolled out Scrum to lift delivery 2.5x")])
    out = honesty.verify(_sel(), phr)
    assert out["A-03"].startswith("Rolled out Scrum")            # accepted


def test_sentence_initial_capital_and_lowercase_synonym_accepted():
    # Заглавная в начале предложения — грамматика, не сущность; строчные синонимы допустимы.
    phr = ResumePhrasing(application_id="a1", bullets=[
        PhrasedBullet(aid="A-04", phrased_text="Managed delivery of 15,000 test-hours")])
    out = honesty.verify(_sel(), phr)
    assert out["A-04"].startswith("Managed delivery")            # accepted
