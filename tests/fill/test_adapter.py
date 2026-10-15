from job_machine.browser.schema import FormField, FormSchema
from job_machine.fill.adapter import map_fields
from job_machine.package.models import DisclosedAnswer, DisclosedConsent


def _answers():
    return [
        DisclosedAnswer(field="Full name", value="Andrey Samoylov"),
        DisclosedAnswer(field="Email", value="a@b.com"),
        DisclosedAnswer(field="Phone", value="+10000000000"),
        DisclosedAnswer(field="English", value="B2"),
        DisclosedAnswer(field="Notice period", value="1 month"),
    ]


def _gh_schema(fields):
    return FormSchema(url="https://boards.greenhouse.io/x/jobs/1", fields=fields,
                      file_inputs=["job_application[resume]"])


def test_greenhouse_standard_fields_and_fullname_split():
    schema = _gh_schema([
        FormField(name="job_application[first_name]", field_type="text", required=True),
        FormField(name="job_application[last_name]", field_type="text", required=True),
        FormField(name="job_application[email]", field_type="email", required=True),
        FormField(name="job_application[phone]", field_type="text", required=False),
        FormField(name="job_application[resume]", field_type="file", required=True),
    ])
    m = map_fields(_answers(), [], schema, "greenhouse")
    assert m.fields["job_application[first_name]"] == "Andrey"
    assert m.fields["job_application[last_name]"] == "Samoylov"
    assert m.fields["job_application[email]"] == "a@b.com"
    assert m.fields["job_application[phone]"] == "+10000000000"
    assert m.resume_field == "job_application[resume]"
    assert m.unmatched_required == []


def test_custom_question_matched_by_label():
    schema = _gh_schema([
        FormField(name="job_application[answers_attributes][0][text_value]",
                  field_type="text", label="Notice period (months)", required=True),
    ])
    m = map_fields(_answers(), [], schema, "greenhouse")
    assert m.fields["job_application[answers_attributes][0][text_value]"] == "1 month"
    assert "Notice period" in m.matched


def test_blocked_fact_required_field_becomes_unmatched():
    schema = _gh_schema([
        FormField(name="job_application[answers_attributes][1][text_value]",
                  field_type="text",
                  label="Are you authorized to work in the EU?", required=True),
    ])
    m = map_fields(_answers(), [], schema, "greenhouse")
    assert m.fields == {}
    assert m.unmatched_required == [
        "job_application[answers_attributes][1][text_value]"]


def test_select_value_matched_to_option_text():
    schema = _gh_schema([
        FormField(name="job_application[answers_attributes][2]", field_type="select",
                  label="English level", required=True,
                  options=["", "A2", "B1", "B2 — Upper intermediate", "C1"]),
    ])
    m = map_fields(_answers(), [], schema, "greenhouse")
    assert m.fields["job_application[answers_attributes][2]"] == "B2 — Upper intermediate"


def test_select_no_matching_option_required_is_unmatched():
    schema = _gh_schema([
        FormField(name="job_application[answers_attributes][3]", field_type="select",
                  label="English level", required=True, options=["", "C1", "C2"]),
    ])
    m = map_fields(_answers(), [], schema, "greenhouse")
    assert "job_application[answers_attributes][3]" in m.unmatched_required


def test_optional_unmatched_is_skipped_not_blocked():
    schema = _gh_schema([
        FormField(name="job_application[answers_attributes][4][text_value]",
                  field_type="text", label="LinkedIn profile", required=False),
    ])
    m = map_fields(_answers(), [], schema, "greenhouse")
    assert m.fields == {}
    assert m.unmatched_required == []


def test_consent_checkbox_not_autochecked_required_blocks():
    schema = _gh_schema([
        FormField(name="job_application[consent]", field_type="checkbox",
                  label="I agree to the privacy policy", required=True),
    ])
    m = map_fields(_answers(), [DisclosedConsent(field="GDPR consent", decision="decline")],
                   schema, "greenhouse")
    assert "job_application[consent]" not in m.fields
    assert m.unmatched_required == ["job_application[consent]"]


def test_ambiguous_label_match_is_unmatched_not_guessed():
    # И "Linux", и "Commercial Linux" — подстроки label → неоднозначно → не угадываем
    # (review MAJOR-1: иначе first-hit по dict мог бы подставить значение в чужое поле).
    answers = [
        DisclosedAnswer(field="Linux", value="None"),
        DisclosedAnswer(field="Commercial Linux", value="None, ops only"),
    ]
    schema = _gh_schema([
        FormField(name="job_application[answers_attributes][9][text_value]",
                  field_type="text", label="Commercial Linux experience", required=True),
    ])
    m = map_fields(answers, [], schema, "greenhouse")
    assert m.fields == {}
    assert "job_application[answers_attributes][9][text_value]" in m.unmatched_required


def test_exact_label_match_preferred_over_substring():
    # Точное совпадение label == vault-поле берётся, даже если есть другой подстрочный кандидат.
    answers = [
        DisclosedAnswer(field="Linux", value="L"),
        DisclosedAnswer(field="Commercial Linux", value="CL"),
    ]
    schema = _gh_schema([
        FormField(name="q", field_type="text", label="Commercial Linux", required=True),
    ])
    m = map_fields(answers, [], schema, "greenhouse")
    assert m.fields["q"] == "CL"


def test_react_select_field_matched_by_literal_question_id_when_label_missing():
    # Кастомные react-select вопросы (job-boards.greenhouse.io) не имеют <label for=id>
    # — inspect.py не может извлечь field.label, только field.name = DOM id
    # ("question_67943985"). Owner заранее ответил на такой вопрос, ответ лёг в
    # application_answer буквально по этому id (см. Adyen/Addepar submit_blocked,
    # аудит 23.07: filled_fields не включал ни один из question_* select-полей).
    answers = [DisclosedAnswer(field="question_67943985", value="No")]
    schema = _gh_schema([
        FormField(name="question_67943985", field_type="select", required=True,
                  options=["", "Yes", "No"]),
    ])
    m = map_fields(answers, [], schema, "greenhouse")
    assert m.fields["question_67943985"] == "No"
    assert m.unmatched_required == []


def test_duplicate_question_fields_matched_independently_by_literal_id():
    # Два разных DOM-поля под один и тот же видимый вопрос ("estimate of preferred
    # annual base salary" дублируется в форме) — каждое со своим question_id и своим
    # локализованным ответом. Матч по имени не завязан на подстрочную неоднозначность
    # label (в отличие от test_ambiguous_label_match_is_unmatched_not_guessed).
    answers = [
        DisclosedAnswer(field="question_67943981",
                        value="36,000 EUR / year (~3,000 EUR/month)"),
        DisclosedAnswer(field="question_67943988",
                        value="36,000 EUR / year (~3,000 EUR/month)"),
    ]
    schema = _gh_schema([
        FormField(name="question_67943981", field_type="text", required=True),
        FormField(name="question_67943988", field_type="text", required=True),
    ])
    m = map_fields(answers, [], schema, "greenhouse")
    assert m.fields["question_67943981"] == "36,000 EUR / year (~3,000 EUR/month)"
    assert m.fields["question_67943988"] == "36,000 EUR / year (~3,000 EUR/month)"
    assert m.unmatched_required == []


def test_name_exact_match_does_not_override_label_semantic_match():
    # Семантические GH-имена (first/last/email/phone) остаются в приоритете — новый
    # literal-id fallback не должен их перехватывать даже если бы совпадение было
    # случайно возможно.
    schema = _gh_schema([
        FormField(name="job_application[first_name]", field_type="text", required=True),
    ])
    m = map_fields(_answers(), [], schema, "greenhouse")
    assert m.fields["job_application[first_name]"] == "Andrey"


def test_unnamed_required_field_is_reported_unmatched():
    """Живой слепок Greenhouse 06.08: 15 required-полей вида field_N с пустым label.
    Они обязаны попасть в unmatched_required — иначе гард mandatory_unknown слеп
    и submit доходит до необратимого клика (ноль подач из 26)."""
    schema = FormSchema(
        url="https://job-boards.greenhouse.io/remotecom/jobs/7331443003",
        fields=[
            FormField(name="field_4", field_type="text", label="", required=True),
            FormField(name="field_11", field_type="text", label=None, required=True),
        ],
    )

    res = map_fields([], [], schema, "greenhouse")

    assert res.unmatched_required == ["field_4", "field_11"]


def test_unnamed_optional_field_is_not_reported():
    """Необязательное безымянное поле блокером не является."""
    schema = FormSchema(
        url="https://job-boards.greenhouse.io/x/jobs/1",
        fields=[FormField(name="field_7", field_type="text", label="", required=False)],
    )

    res = map_fields([], [], schema, "greenhouse")

    assert res.unmatched_required == []
