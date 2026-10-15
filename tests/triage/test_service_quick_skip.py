from job_machine.triage.service import _quick_skip, _role_matches


def test_role_matches_generic_team_leader_no_longer_false_positive():
    # Баг: "Team Lead" из профиля матчил "Engineering Team Leader" как substring.
    # После фикса (word-boundary) — не матчит: title_mismatch.
    roles = ["QA", "Team Lead", "Delivery Manager"]
    assert _role_matches("Engineering Team Leader", roles) is False
    assert _quick_skip("remote", "Engineering Team Leader", roles) == "title_mismatch"


def test_role_matches_legitimate_team_lead_still_matches():
    roles = ["Team Lead"]
    assert _role_matches("Team Lead, Platform", roles) is True
    assert _quick_skip("remote", "Team Lead, Platform", roles) is None


def test_role_matches_none_title_still_true():
    assert _role_matches(None, ["QA"]) is True


def test_role_matches_qa_does_not_match_qatar():
    assert _role_matches("Qatar Systems Lead", ["QA"]) is False
