# coding: utf-8
from job_machine.package.answer_resolve import merge_answers
from job_machine.package.models import AnswerRecord


def _a(field, value, state="locked"):
    return AnswerRecord(field=field, value=value, state=state)


def test_per_app_overrides_global_same_field():
    g = [_a("Full name", "Andrey S"), _a("Preferred location", "Anywhere")]
    app = [_a("Preferred location", "Remote, Germany")]
    out = {a.field: a.value for a in merge_answers(g, app)}
    assert out["Preferred location"] == "Remote, Germany"
    assert out["Full name"] == "Andrey S"


def test_override_is_case_and_space_insensitive():
    g = [_a("Preferred  Location", "Anywhere")]
    app = [_a("preferred location", "Berlin")]
    out = merge_answers(g, app)
    assert len(out) == 1
    assert out[0].value == "Berlin"


def test_distinct_fields_all_kept():
    g = [_a("Email", "a@b.c")]
    app = [_a("How did you hear about this role?", "Job Board")]
    assert len(merge_answers(g, app)) == 2


def test_empty_app_returns_global():
    g = [_a("Email", "a@b.c")]
    assert [x.value for x in merge_answers(g, [])] == ["a@b.c"]
