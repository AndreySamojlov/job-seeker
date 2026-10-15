"""Тесты Pydantic-схем HandoffRequest и HandoffResult."""
import pytest

from job_machine.browser.schema import HandoffRequest, HandoffResult


def test_handoff_request_requires_url():
    req = HandoffRequest(url="https://example.com/apply")
    assert req.url == "https://example.com/apply"


def test_handoff_request_missing_url():
    with pytest.raises(Exception):
        HandoffRequest()


def test_handoff_result_minimal():
    res = HandoffResult(session_id="s1", status="handoff")
    assert res.session_id == "s1"
    assert res.status == "handoff"
    assert res.novnc_url is None


def test_handoff_result_with_novnc():
    res = HandoffResult(
        session_id="s1",
        status="handoff",
        novnc_url="http://lab-vm:6080/vnc.html?token=s1",
    )
    assert res.novnc_url == "http://lab-vm:6080/vnc.html?token=s1"
