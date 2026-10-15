from job_machine.resume.models import (
    Contact, PhrasedBullet, PhrasingRequest, ResumePhrasing, ResumeSelection,
    SelectedBullet, SelectedPosition, SkillGroup,
)


def test_selection_round_trips():
    sel = ResumeSelection(
        application_id="a1", headline="Head of QA / IT Delivery Leader",
        positions=[SelectedPosition(
            pid="P-01", company="NSD", title="Head of QA / IT Delivery Leader",
            start="2024-09", end="present", location="Moscow",
            bullets=[SelectedBullet(aid="A-04", source_text="Throughput delivered",
                                    source_metric="15,000 test-hours", safe_use="resume")])],
        skill_groups=[SkillGroup(category="skill", items=["QA & test strategy — Expert"])])
    assert sel.positions[0].bullets[0].aid == "A-04"
    assert sel.model_dump()["headline"].startswith("Head of QA")


def test_phrasing_contract():
    req = PhrasingRequest(application_id="a1", headline="H",
                          bullets=[{"aid": "A-04", "source_text": "t", "source_metric": "m"}])
    assert req.bullets[0]["aid"] == "A-04"
    phr = ResumePhrasing(application_id="a1",
                         bullets=[PhrasedBullet(aid="A-04", phrased_text="reworded")])
    assert phr.bullets[0].phrased_text == "reworded"


def test_contact_all_optional():
    c = Contact()
    assert c.email is None and c.phone is None and c.location is None and c.linkedin is None
    c2 = Contact(email="a@b.com", location="Berlin")
    assert c2.email == "a@b.com"


def test_selection_has_contact_and_summary_defaults():
    s = ResumeSelection(application_id="a", headline="H")
    assert s.contact is None
    assert s.summary == ""


def test_phrasing_request_has_jd_summary():
    r = PhrasingRequest(application_id="a", headline="H")
    assert r.jd_summary == ""
