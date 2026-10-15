from job_machine.fill.models import FillRunSummary, MappingResult


def test_mapping_result_defaults():
    m = MappingResult()
    assert m.fields == {}
    assert m.resume_field is None
    assert m.unmatched_required == []
    assert m.matched == []


def test_mapping_result_carries_fields():
    m = MappingResult(
        fields={"job_application[email]": "a@b.com"},
        resume_field="job_application[resume]",
        unmatched_required=["Work authorization"],
        matched=["Email"],
    )
    assert m.fields["job_application[email]"] == "a@b.com"
    assert m.resume_field == "job_application[resume]"
    assert m.unmatched_required == ["Work authorization"]
    assert m.matched == ["Email"]


def test_run_summary_counters():
    s = FillRunSummary()
    assert (s.pulled, s.pre_submit_ready, s.blocked, s.errors) == (0, 0, 0, 0)
    s.pulled += 2
    s.blocked += 1
    assert s.pulled == 2 and s.blocked == 1
