"""Единый источник allow-list оповещений (§3-обоснование — см. спеку).

EVENT_KIND: event_type кураторского события → kind сообщения. И render, и store
опираются на этот словарь, чтобы список типов не разъезжался.
FILL_BLOCKED_NOTIFY: application.fill_blocked уведомляет ТОЛЬКО при этих
blocker-значениях (человеко-действенные; broken_flow/throttle — шум, исключены).
captcha/mfa/anti_bot включены: resume_after_handoff при still_blocked пишет
именно эти current_blocker-значения, а browser-сессия в этот момент физически
жива и ждёт владельца — это такой же человеко-действенный случай, как
handoff_manual/mandatory_unknown, а не шум.
"""

EVENT_KIND = {
    "application.approval_requested": "approval_requested",
    "application.submitted": "submitted",
    "application.handoff_manual": "blocked",
    "application.fill_blocked": "blocked",
    "application.rejected": "reply_rejected",
    "application.interview_scheduled": "reply_interview",
}

FILL_BLOCKED_NOTIFY = ("mandatory_unknown", "captcha", "mfa", "anti_bot")
