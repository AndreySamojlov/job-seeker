from job_machine.cloud.models import (
    CloudAchievement, CloudPosition, CloudSkill, ExperienceCloud,
)


def test_position_fields():
    p = CloudPosition(pid="P-01", company="NSD", title="Head of QA",
                      start="2024-09", end="present", location="Moscow", summary="x")
    assert p.pid == "P-01" and p.end == "present"


def test_achievement_defaults():
    a = CloudAchievement(aid="A-01", pid="P-01", text="did x")
    assert a.metric == "" and a.status == "" and a.claims == "" and a.safe_use == ""


def test_skill_defaults():
    s = CloudSkill(name="Python", category="skill")
    assert s.framing == "" and s.evidence == "" and s.safe_use == ""


def test_experience_cloud_container():
    c = ExperienceCloud()
    assert c.positions == [] and c.achievements == [] and c.skills == []
