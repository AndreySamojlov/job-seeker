import pytest

pytest.importorskip("pydantic")

from pydantic import ValidationError

from job_machine.browser.schema import (
    FillRequest,
    FillResult,
    FormField,
    FormSchema,
    InspectRequest,
    InspectResult,
    SessionInfo,
)


def test_form_field_requires_name_and_type():
    with pytest.raises(ValidationError):
        FormField(label="x")


def test_form_schema_roundtrip():
    schema = FormSchema(
        url="file:///f.html",
        fields=[FormField(name="full_name", field_type="text", required=True)],
        file_inputs=["resume"],
        consent_checkboxes=["consent"],
        submit_buttons=["Submit Application"],
    )
    again = FormSchema.model_validate(schema.model_dump())
    assert again.fields[0].name == "full_name"
    assert again.file_inputs == ["resume"]


def test_fill_result_defaults_to_stopped():
    assert FillResult(filled=["full_name"]).stopped_before_submit is True


def test_request_models_minimal():
    assert InspectRequest(session_id="s", url="u").url == "u"
    assert FillRequest(session_id="s").fields == {}
    assert SessionInfo(session_id="s", status="open").current_url is None
    assert InspectResult().blocker is None


def test_inspect_request_navigate_defaults_true():
    req = InspectRequest(session_id="s", url="u")
    assert req.navigate is True


def test_inspect_request_navigate_false_without_url():
    req = InspectRequest(session_id="s", navigate=False)
    assert req.url is None
    assert req.navigate is False


def test_inspect_request_navigate_true_requires_url():
    """navigate=True (дефолт) без url — чистая 422 на границе API, а не грязный
    500 из Playwright (page.goto(None, ...))."""
    with pytest.raises(ValidationError):
        InspectRequest(session_id="s")


def test_form_field_group_label_defaults_to_none():
    assert FormField(name="q[]", field_type="checkbox").group_label is None


def test_form_field_group_label_settable():
    f = FormField(name="q[]", field_type="checkbox", group_label="Point of Data Transfer")
    assert f.group_label == "Point of Data Transfer"
