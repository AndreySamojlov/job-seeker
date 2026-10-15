from job_machine.browser.schema import FormField, FormSchema
from job_machine.fill.adapter import map_fields
from job_machine.package.models import DisclosedAnswer


def _schema(fields, consent_checkboxes=None):
    return FormSchema(url="https://x", fields=fields,
                      consent_checkboxes=consent_checkboxes or [])


def _loc_group():
    return [FormField(name="q1[]", field_type="checkbox", label=lbl, required=True)
            for lbl in ("Remote, Germany", "Berlin, Germany", "Warsaw, Poland")]


def test_checkbox_option_matching_disclosed_value_is_filled():
    ans = [DisclosedAnswer(field="Which is your preferred location for this role?",
                           value="Remote, Germany")]
    res = map_fields(ans, [], _schema(_loc_group()))
    assert res.fields.get("q1[]") == "Remote, Germany"
    assert "q1[]" not in res.unmatched_required


def test_checkbox_group_no_match_required_is_unmatched_once():
    ans = [DisclosedAnswer(field="x", value="Nowhere")]
    res = map_fields(ans, [], _schema(_loc_group()))
    assert "q1[]" not in res.fields
    assert res.unmatched_required.count("q1[]") == 1


def test_consent_checkbox_never_filled_even_if_value_matches():
    cb = [FormField(name="privacy[]", field_type="checkbox",
                    label="I agree to the Privacy Notice", required=True)]
    ans = [DisclosedAnswer(field="x", value="I agree to the Privacy Notice")]
    res = map_fields(ans, [], _schema(cb, consent_checkboxes=["privacy[]"]))
    assert "privacy[]" not in res.fields
    assert "privacy[]" in res.unmatched_required


def test_consent_by_label_hint_never_filled():
    cb = [FormField(name="c1", field_type="checkbox",
                    label="I consent to background check", required=True)]
    ans = [DisclosedAnswer(field="x", value="I consent to background check")]
    res = map_fields(ans, [], _schema(cb))
    assert "c1" not in res.fields
    assert "c1" in res.unmatched_required


def test_consent_by_broadened_hint_accept_not_filled():
    from job_machine.browser.schema import FormField, FormSchema
    from job_machine.package.models import DisclosedAnswer
    from job_machine.fill.adapter import map_fields
    cb = [FormField(name="acc", field_type="checkbox", label="Accept", required=True)]
    ans = [DisclosedAnswer(field="x", value="Accept")]
    res = map_fields(ans, [], FormSchema(url="https://x", fields=cb))
    assert "acc" not in res.fields
    assert "acc" in res.unmatched_required


def test_standing_gdpr_demographic_consent_auto_checked():
    cb = [FormField(name="gdpr_demographic_data_consent_given", field_type="checkbox",
                    label="Acknowledge/Confirm", required=True)]
    res = map_fields([], [], _schema(cb))
    assert "gdpr_demographic_data_consent_given" in res.auto_consents
    assert "gdpr_demographic_data_consent_given" not in res.unmatched_required


def test_standing_gdpr_processing_consent_auto_checked():
    cb = [FormField(name="gdpr_processing_consent_given", field_type="checkbox",
                    label="Acknowledge/Confirm", required=True)]
    res = map_fields([], [], _schema(cb))
    assert "gdpr_processing_consent_given" in res.auto_consents
    assert "gdpr_processing_consent_given" not in res.unmatched_required


def test_existing_select_text_still_work():
    fields = [FormField(name="email", field_type="email", label="Email", required=True),
              FormField(name="loc", field_type="select", label="Location",
                        required=True, options=["Remote, Germany", "Berlin"])]
    ans = [DisclosedAnswer(field="Email", value="a@b.c"),
           DisclosedAnswer(field="Location", value="Remote, Germany")]
    res = map_fields(ans, [], _schema(fields))
    assert res.fields["email"] == "a@b.c"
    assert res.fields["loc"] == "Remote, Germany"


def test_standing_label_pdn_consent_single_option_auto_checked():
    cb = [FormField(name="job_application_answers_attributes_7_boolean_value",
                    field_type="checkbox", label="Acknowledge/Confirm",
                    group_label="Point of Data Transfer", required=True)]
    res = map_fields([], [], _schema(cb))
    assert "job_application_answers_attributes_7_boolean_value" in res.auto_consents
    assert "job_application_answers_attributes_7_boolean_value" not in res.unmatched_required


def test_standing_label_ai_responsible_use_policy_auto_checked():
    cb = [FormField(name="job_application_answers_attributes_9_boolean_value",
                    field_type="checkbox", label="Acknowledge/Confirm",
                    group_label="AI Responsible Use Policy", required=True)]
    res = map_fields([], [], _schema(cb))
    assert "job_application_answers_attributes_9_boolean_value" in res.auto_consents


def test_standing_label_review_company_privacy_policy_pattern_auto_checked():
    cb = [FormField(name="job_application_answers_attributes_3_boolean_value",
                    field_type="checkbox", label="Confirm",
                    group_label="Review Acme Recruitment Privacy Policy", required=True)]
    res = map_fields([], [], _schema(cb))
    assert "job_application_answers_attributes_3_boolean_value" in res.auto_consents


def test_standing_label_non_matching_group_label_stays_unmatched():
    cb = [FormField(name="job_application_answers_attributes_4_boolean_value",
                    field_type="checkbox", label="Acknowledge/Confirm",
                    group_label="Are you willing to relocate?", required=True)]
    res = map_fields([], [], _schema(cb))
    assert "job_application_answers_attributes_4_boolean_value" not in res.auto_consents
    assert "job_application_answers_attributes_4_boolean_value" in res.unmatched_required


def test_standing_label_none_group_label_stays_unmatched():
    """inspect.py эвристика ничего не нашла (group_label=None) — статус-кво, не auto-check."""
    cb = [FormField(name="q_unknown", field_type="checkbox", label="Acknowledge/Confirm",
                    required=True)]
    res = map_fields([], [], _schema(cb))
    assert "q_unknown" not in res.auto_consents
    assert "q_unknown" in res.unmatched_required


def test_standing_label_multi_option_group_never_auto_checked():
    """Жёсткий гейт: >=2 опции — эвристика не применяется, даже если group_label матчит."""
    cb = [
        FormField(name="privacy_opts", field_type="checkbox", label="Acknowledge/Confirm",
                  group_label="Privacy Disclosure", required=True),
        FormField(name="privacy_opts", field_type="checkbox", label="Decline",
                  group_label="Privacy Disclosure", required=True),
    ]
    res = map_fields([], [], _schema(cb))
    assert "privacy_opts" not in res.auto_consents
    assert "privacy_opts" in res.unmatched_required


def test_demographic_group_with_decline_option_is_auto_selected():
    # Greenhouse EEO gender/race question (реальный DOM, сверено 2026-07-07/переприменено
    # 2026-07-24) — нет disclosed-значения, совпадающего с опцией, но есть decline-опция.
    cb = [FormField(name="question_56152[]", field_type="checkbox", label=lbl, required=True)
          for lbl in ("Male", "Female", "Non-binary", "Prefer not to say")]
    res = map_fields([], [], _schema(cb))
    assert res.fields.get("question_56152[]") == "Prefer not to say"
    assert "question_56152[]" not in res.unmatched_required


def test_demographic_group_alt_decline_wording_is_auto_selected():
    # Twilio veteran/disability self-ID wording (реальный DOM, сверено 2026-07-07).
    cb = [FormField(name="question_veteran[]", field_type="checkbox", label=lbl, required=True)
          for lbl in ("I am a protected veteran", "I am not a protected veteran",
                      "I don't wish to answer")]
    res = map_fields([], [], _schema(cb))
    assert res.fields.get("question_veteran[]") == "I don't wish to answer"
    assert "question_veteran[]" not in res.unmatched_required


def test_demographic_group_without_decline_option_still_blocks():
    cb = [FormField(name="question_gender[]", field_type="checkbox", label=lbl, required=True)
          for lbl in ("Male", "Female")]
    res = map_fields([], [], _schema(cb))
    assert "question_gender[]" not in res.fields
    assert "question_gender[]" in res.unmatched_required


def test_disclosed_value_still_preferred_over_decline_option():
    # Реальное раскрытое значение матчится к опции ДО того, как рассматривается
    # decline-фолбэк — decline не должен перебивать честный явный ответ.
    cb = [FormField(name="question_gender[]", field_type="checkbox", label=lbl, required=True)
          for lbl in ("Male", "Female", "Prefer not to say")]
    ans = [DisclosedAnswer(field="Gender", value="Male")]
    res = map_fields(ans, [], _schema(cb))
    assert res.fields.get("question_gender[]") == "Male"


def test_preferred_location_group_picks_remote_option():
    # JetBrains "Which is your preferred location for this role?" (реальный DOM,
    # сверено 2026-07-24) — список городов конкретной компании, среди них Remote.
    cb = [FormField(name="question_8602604101[]", field_type="checkbox", label=lbl,
                    group_label="Which is your preferred location for this role? *",
                    required=True)
          for lbl in ("Amsterdam, Netherlands", "Berlin, Germany", "Remote, Germany",
                      "Warsaw, Poland")]
    res = map_fields([], [], _schema(cb))
    assert res.fields.get("question_8602604101[]") == "Remote, Germany"
    assert "question_8602604101[]" not in res.unmatched_required


def test_preferred_location_group_without_remote_picks_first_option():
    cb = [FormField(name="question_x[]", field_type="checkbox", label=lbl,
                    group_label="Which is your preferred location for this role? *",
                    required=True)
          for lbl in ("Amsterdam, Netherlands", "Berlin, Germany", "Warsaw, Poland")]
    res = map_fields([], [], _schema(cb))
    assert res.fields.get("question_x[]") == "Amsterdam, Netherlands"


def test_disclosed_value_still_preferred_over_location_default():
    cb = [FormField(name="question_y[]", field_type="checkbox", label=lbl,
                    group_label="Which is your preferred location for this role? *",
                    required=True)
          for lbl in ("Amsterdam, Netherlands", "Berlin, Germany", "Remote, Germany")]
    ans = [DisclosedAnswer(field="Location preference", value="Berlin, Germany")]
    res = map_fields(ans, [], _schema(cb))
    assert res.fields.get("question_y[]") == "Berlin, Germany"


def test_other_option_selected_when_no_disclosed_match():
    # Capco "What is your current location? *" (реальный DOM, сверено 2026-07-24) —
    # ни один диск-ответ не совпал с конкретной опцией (кандидат не в Польше), но есть
    # честный catch-all "Other" — владелец авторизовал общий фолбэк 2026-07-24.
    cb = [FormField(name="question_68058602[]", field_type="checkbox", label=lbl,
                    group_label="What is your current location? *", required=True)
          for lbl in ("Poland", "Other")]
    res = map_fields([], [], _schema(cb))
    assert res.fields.get("question_68058602[]") == "Other"
    assert "question_68058602[]" not in res.unmatched_required


def test_other_option_selected_for_how_did_you_hear_group():
    # In The Pocket "How did you hear about this job? *" (реальный DOM, 2026-07-24).
    cb = [FormField(name="question_67812395[]", field_type="checkbox", label=lbl,
                    group_label="How did you hear about this job? *", required=True)
          for lbl in ("In The Pocket Employee", "In The Pocket Website", "LinkedIn",
                      "Facebook", "Other")]
    res = map_fields([], [], _schema(cb))
    assert res.fields.get("question_67812395[]") == "Other"


def test_other_option_not_selected_for_demographic_group_without_decline_wording():
    # Гейт честности: "Other" в gender/race-группе МОЖЕТ быть настоящей идентичностью,
    # а не catch-all "ничего не подошло" — без явной decline-опции (looks_like_decline_option)
    # фолбэк на "Other" здесь НЕ применяется, группа остаётся unmatched_required. group_label
    # намеренно ставим ПОД allowlist ("current location"), чтобы тест реально проверял
    # demographic-гейт, а не просто отсутствие в allowlist.
    cb = [FormField(name="question_gender2[]", field_type="checkbox", label=lbl,
                    group_label="What is your current location? *", required=True)
          for lbl in ("Male", "Female", "Other")]
    res = map_fields([], [], _schema(cb))
    assert "question_gender2[]" not in res.fields
    assert "question_gender2[]" in res.unmatched_required


def test_other_option_not_selected_without_allowlisted_question_shape():
    # Code-review finding (2026-07-24): "Other"-фолбэк — allowlist по group_label
    # (как и preferred-location), НЕ permissive-with-denylist. Произвольный вопрос с
    # опцией "Other", не входящий в allowlist известных безопасных форм, остаётся
    # unmatched_required — иначе фолбэк рисковал бы сработать на blocked-факте.
    cb = [FormField(name="question_random[]", field_type="checkbox", label=lbl,
                    group_label="What is your favorite office snack? *", required=True)
          for lbl in ("Chips", "Fruit", "Other")]
    res = map_fields([], [], _schema(cb))
    assert "question_random[]" not in res.fields
    assert "question_random[]" in res.unmatched_required


def test_other_option_not_selected_for_work_authorization_question():
    # Главная находка code-review: work authorization — blocked-факт (§3, docstring
    # модуля). "Other" на этом вопросе — субстантивное утверждение о статусе, не
    # нейтральный "ничего из перечисленного". Allowlist-гейт исключает это в принципе
    # (group_label не входит в allowlist), но тест фиксирует это явно.
    cb = [FormField(name="question_workauth[]", field_type="checkbox", label=lbl,
                    group_label="What is your work authorization status? *", required=True)
          for lbl in ("Citizen", "Permanent Resident", "Requires sponsorship", "Other")]
    res = map_fields([], [], _schema(cb))
    assert "question_workauth[]" not in res.fields
    assert "question_workauth[]" in res.unmatched_required


def test_other_option_not_selected_for_sponsorship_question():
    cb = [FormField(name="question_sponsor[]", field_type="checkbox", label=lbl,
                    group_label="Will you now or in the future require sponsorship? *",
                    required=True)
          for lbl in ("Yes", "No", "Other")]
    res = map_fields([], [], _schema(cb))
    assert "question_sponsor[]" not in res.fields
    assert "question_sponsor[]" in res.unmatched_required


def test_other_option_not_selected_for_german_level_question():
    cb = [FormField(name="question_german[]", field_type="checkbox", label=lbl,
                    group_label="What is your German language level? *", required=True)
          for lbl in ("A1", "B2", "Native", "Other")]
    res = map_fields([], [], _schema(cb))
    assert "question_german[]" not in res.fields
    assert "question_german[]" in res.unmatched_required


def test_disclosed_value_still_preferred_over_other_fallback():
    cb = [FormField(name="question_loc2[]", field_type="checkbox", label=lbl,
                    group_label="What is your current location? *", required=True)
          for lbl in ("Poland", "Other")]
    ans = [DisclosedAnswer(field="Current location", value="Poland")]
    res = map_fields(ans, [], _schema(cb))
    assert res.fields.get("question_loc2[]") == "Poland"


def test_unrelated_group_without_location_hint_still_blocks():
    # Без group_label-хинта "preferred location" фолбэк не применяется — обычная
    # неотвеченная required-группа остаётся unmatched (статус-кво).
    cb = [FormField(name="question_z[]", field_type="checkbox", label=lbl,
                    group_label="Which benefits are most important to you? *",
                    required=True)
          for lbl in ("Health insurance", "Remote work stipend", "Gym membership")]
    res = map_fields([], [], _schema(cb))
    assert "question_z[]" not in res.fields
    assert "question_z[]" in res.unmatched_required
