from job_machine.notify import models


def test_event_kind_maps_curated_types():
    assert models.EVENT_KIND["application.approval_requested"] == "approval_requested"
    assert models.EVENT_KIND["application.submitted"] == "submitted"
    assert models.EVENT_KIND["application.handoff_manual"] == "blocked"
    assert models.EVENT_KIND["application.fill_blocked"] == "blocked"
    # Не-кураторские типы отсутствуют.
    assert "application.approval_payload_drift" not in models.EVENT_KIND


def test_fill_blocked_notify_is_human_actionable_only():
    assert models.FILL_BLOCKED_NOTIFY == ("mandatory_unknown", "captcha", "mfa", "anti_bot")


def test_fill_blocked_notify_includes_live_handoff_blockers():
    """captcha/mfa/anti_bot — resume_after_handoff still_blocked оставляет
    browser-сессию живой и ждущей владельца; это тоже человеко-действенный
    случай, не шум (в отличие от broken_flow/throttle)."""
    assert "captcha" in models.FILL_BLOCKED_NOTIFY
    assert "mfa" in models.FILL_BLOCKED_NOTIFY
    assert "anti_bot" in models.FILL_BLOCKED_NOTIFY
