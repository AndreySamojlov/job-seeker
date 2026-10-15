from job_machine.consent import looks_like_decline_option, looks_like_standing_label_consent


def test_point_of_data_transfer_matches():
    assert looks_like_standing_label_consent("Point of Data Transfer") is True


def test_privacy_disclosure_matches():
    assert looks_like_standing_label_consent("Privacy Disclosure") is True


def test_personal_information_policy_matches():
    assert looks_like_standing_label_consent("Personal Information Policy") is True


def test_candidate_privacy_policy_matches():
    assert looks_like_standing_label_consent("Candidate Privacy Policy") is True


def test_ai_responsible_use_policy_matches():
    assert looks_like_standing_label_consent("AI Responsible Use Policy") is True


def test_applicant_privacy_policy_matches():
    """Twilio-формулировка (2026-07-16): "...in accordance with the Twilio Applicant
    Privacy Policy." — не начинается с "review", ловится только по substring."""
    label = ('By clicking the "Acknowledge" button, you acknowledge that Twilio '
             'processes data in accordance with the Twilio Applicant Privacy Policy.')
    assert looks_like_standing_label_consent(label) is True


def test_review_company_privacy_policy_pattern_matches():
    assert looks_like_standing_label_consent("Review Acme Recruitment Privacy Policy") is True


def test_review_company_privacy_notice_pattern_matches():
    assert looks_like_standing_label_consent("Please review our Privacy Notice") is True


def test_unrelated_label_does_not_match():
    assert looks_like_standing_label_consent("How did you hear about us?") is False


def test_generic_agree_hint_alone_does_not_match_standing_label():
    """§3: широкий CONSENT_HINTS ("agree"/"terms") — не то же самое, что узкий
    standing-label allowlist. Обычное согласие с terms остаётся неавто."""
    assert looks_like_standing_label_consent("I agree to the Terms of Service") is False


def test_none_label_does_not_match():
    assert looks_like_standing_label_consent(None) is False


def test_bundled_privacy_and_marketing_consent_does_not_match():
    """Code-review finding 2026-07-15: regex был незаякорен и матчил бандл
    privacy+marketing — marketing НЕ должен авто-проставляться отдельно (§3)."""
    label = "Review the role, then confirm you accept our privacy notice and consent to marketing emails"
    assert looks_like_standing_label_consent(label) is False


def test_confidential_information_matches():
    """Zscaler-формулировка (реальный DOM, 2026-07-24): единственная опция "I Agree" на
    question-level label "Zscaler Confidential Information" — авторизация владельца
    2026-07-24 (третья категория стоячего согласия, см. CLAUDE.md §3)."""
    assert looks_like_standing_label_consent("Zscaler Confidential Information") is True


def test_generic_company_privacy_policy_matches_without_review_prefix():
    """Zscaler-формулировка (реальный DOM, 2026-07-24): "Zscaler Privacy Policy" —
    не начинается с "review", в отличие от Acme-примера выше. Уже разрешённая категория
    (privacy policy/notice), просто более узкий якорь пропускал этот случай."""
    assert looks_like_standing_label_consent("Zscaler Privacy Policy") is True


def test_decline_prefer_not_to_say_matches():
    assert looks_like_decline_option("Prefer not to say") is True


def test_decline_dont_wish_to_answer_matches():
    assert looks_like_decline_option("I don't wish to answer") is True


def test_decline_unrelated_option_does_not_match():
    assert looks_like_decline_option("Male") is False


def test_decline_none_does_not_match():
    assert looks_like_decline_option(None) is False


def test_bundled_terms_of_service_and_privacy_policy_does_not_match():
    """Mirror of the 2026-07-15 finding, other order: dropping the "review ..."
    anchor (2026-07-24) must not let a bundled ToS+privacy label through."""
    assert looks_like_standing_label_consent(
        "I accept the Terms of Service and Privacy Policy") is False


def test_bundled_marketing_and_privacy_policy_last_does_not_match():
    """Privacy phrase LAST this time — the \\W*$ end-anchor alone doesn't catch this,
    marketing must be excluded explicitly."""
    assert looks_like_standing_label_consent(
        "I consent to marketing communications and our Privacy Policy") is False


def test_bundled_newsletter_and_privacy_policy_does_not_match():
    assert looks_like_standing_label_consent(
        "I agree to receive newsletters and accept the Privacy Policy") is False


def test_confidential_information_in_background_check_context_does_not_match():
    assert looks_like_standing_label_consent(
        "I authorize a background check which may reveal confidential information "
        "about me") is False


def test_confidential_information_in_credit_check_context_does_not_match():
    assert looks_like_standing_label_consent(
        "I understand this role involves handling confidential information and "
        "consent to a credit check") is False


def test_confidential_information_third_party_sharing_does_not_match():
    assert looks_like_standing_label_consent(
        "I consent to sharing my confidential information with third-party "
        "partners") is False
