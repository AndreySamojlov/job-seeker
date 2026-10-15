from job_machine.ats import greenhouse_questions as gq

_PAYLOAD = {
    "questions": [
        {"label": "First Name", "required": True, "fields": [{"name": "first_name"}]},
        {"label": "Which is your preferred location for this role?", "required": True,
         "fields": [{"name": "question_8602604101[]",
                     "values": [{"label": "Remote, Germany"}, {"label": "Berlin, Germany"}]}]},
        {"label": "Cover Letter", "required": False,
         "fields": [{"name": "cover_letter"}, {"name": "cover_letter_text"}]},
    ]
}


def test_parse_questions_extracts_label_required_fields_options():
    out = gq.parse_questions(_PAYLOAD)
    assert len(out) == 3
    loc = [q for q in out if q["label"].startswith("Which")][0]
    assert loc["required"] is True
    assert loc["fields"] == ["question_8602604101[]"]
    assert loc["options"] == ["Remote, Germany", "Berlin, Germany"]
    fn = [q for q in out if q["label"] == "First Name"][0]
    assert fn["options"] == []


def test_questions_url_appends_param():
    assert gq._questions_url("https://x/v1/boards/a/jobs/1") == \
        "https://x/v1/boards/a/jobs/1?questions=true"
    assert gq._questions_url("https://x/jobs/1?foo=bar") == \
        "https://x/jobs/1?foo=bar&questions=true"
