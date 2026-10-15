from job_machine.browser.schema import SubmitResult, submission_proof_missing


def _complete_proof(**overrides):
    payload = {
        "submitted": True,
        "click_performed": True,
        "confirmation_url": "https://boards.example/jobs/1/confirmation",
        "confirmation_signal": "confirmation_url",
        "form_absent": True,
        "errors_absent": True,
        "screenshot_path": "/data/artifacts/browser/x_confirm.png",
    }
    payload.update(overrides)
    return SubmitResult(**payload)


def test_complete_proof_has_no_missing_parts():
    assert submission_proof_missing(_complete_proof()) == []


def test_missing_click_is_reported():
    assert "click_performed" in submission_proof_missing(
        _complete_proof(click_performed=False))


def test_missing_signal_is_reported():
    assert "confirmation_signal" in submission_proof_missing(
        _complete_proof(confirmation_signal=None))


def test_form_still_present_is_reported():
    assert "form_absent" in submission_proof_missing(
        _complete_proof(form_absent=False))


def test_errors_present_is_reported():
    assert "errors_absent" in submission_proof_missing(
        _complete_proof(errors_absent=False))


def test_missing_screenshot_is_reported():
    assert "screenshot_path" in submission_proof_missing(
        _complete_proof(screenshot_path=""))


def test_defaults_are_absent_not_present():
    assert set(submission_proof_missing(SubmitResult())) == {
        "click_performed", "confirmation_signal",
        "form_absent", "errors_absent", "screenshot_path",
    }
