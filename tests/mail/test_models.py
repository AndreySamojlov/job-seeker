from job_machine.mail.models import EmailInput, ReplyClassification


def test_reply_classification_allows_null_application_id():
    rc = ReplyClassification(application_id=None, candidate_id=None,
                              category="other", confidence=0.2)
    assert rc.category == "other"


def test_email_input_requires_uid():
    email = EmailInput(uid=42, from_addr="hr@acme.com", subject="Update",
                        body="Thanks for applying.")
    assert email.uid == 42
