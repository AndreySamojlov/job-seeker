from job_machine.watchlist.classify import is_globally_open


def test_red_flag_country_residence_disqualifies():
    result = is_globally_open("Must be based in the United States to apply.")
    assert result.qualifies is False


def test_red_flag_remote_region_only_disqualifies():
    result = is_globally_open("This is a Remote (US Only) position.")
    assert result.qualifies is False


def test_red_flag_timezone_overlap_disqualifies():
    result = is_globally_open("Candidates must overlap with EST business hours.")
    assert result.qualifies is False


def test_generic_overlap_requirement_does_not_disqualify():
    result = is_globally_open(
        "Working hours must overlap with the rest of the team for at least 4 hours a day."
    )
    assert result.qualifies is True


def test_explicit_global_phrase_qualifies_with_flag():
    result = is_globally_open(
        "We are a fully distributed team — work from anywhere in the world!"
    )
    assert result.qualifies is True
    assert result.explicit_global is True


def test_neutral_description_qualifies_without_flag():
    result = is_globally_open(
        "Remote position, competitive salary, join our engineering team."
    )
    assert result.qualifies is True
    assert result.explicit_global is False


def test_none_description_qualifies_without_flag():
    result = is_globally_open(None)
    assert result.qualifies is True
    assert result.explicit_global is False
