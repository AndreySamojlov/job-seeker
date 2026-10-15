"""Allowlist кодов, которые submit-путь вправе писать в submission_attempt.

Прежние db-тесты этого файла проверяли pull_approved / record_submitted /
record_submit_blocked — функции удалены вместе с ними: вызывающих у них не осталось
после перехода на claim → mark_clicking → finalize_*, а record_submitted писал
state='submitted' вообще без проверки доказательства, то есть ровно то поведение,
ради устранения которого делался срез.
"""
import pytest

from job_machine.submit import store


# Значения, которые реально доходят до submission_attempt.failure_signal.
# Источники: browser/blockers.py::BLOCKERS (классификация страницы),
# submit/service.py::_submit_claim (доменные блокеры), submit/gate.py (имена гардов),
# submit/service.py + recover_stale_attempts (исходы после клика).
_REAL_FAILURE_CODES = [
    "captcha", "mfa", "anti_bot", "account_required", "login_wall",
    "vacancy_removed", "ambiguous", "broken_flow", "mandatory_unknown",
    "manifest_integrity_mismatch", "destination_redirect",
    "NoSubmitWithoutApproval", "NoSubmitIfPayloadHashChanged",
    "NoSubmitAfterApprovalExpiry", "NoResumeUploadWithoutHashMatch",
    "ValidApplicationId",
    "no_confirmation", "submit_unknown", "unmatched", "native_invalid",
    "aria_invalid", "timeout", "lease_expired",
]


@pytest.mark.parametrize("code", _REAL_FAILURE_CODES)
def test_real_blocker_survives_allowlist(code):
    """Смысл allowlist — не пускать в БД неконтролируемую строку, а не терять диагностику.

    Раньше в нём не было НИ ОДНОГО реального блокера submit-пути, поэтому captcha,
    mfa, mandatory_unknown, destination_redirect, manifest_integrity_mismatch и имена
    гардов схлопывались в леджере попыток в 'broken_flow'.
    """
    assert store.safe_failure_code(code, "broken_flow") == code


def test_uncontrolled_string_still_falls_back():
    """Свойство allowlist сохранено: произвольный текст из браузера в БД не попадает."""
    assert store.safe_failure_code(
        "TimeoutError: waiting for locator('#apply') exceeded 30000ms",
        "broken_flow") == "broken_flow"
    assert store.safe_failure_code(None, "submit_unknown") == "submit_unknown"
