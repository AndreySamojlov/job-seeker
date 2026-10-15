import dataclasses

import pytest

from job_machine.guards.base import Decision, NextAction, GuardResult
from job_machine.guards.context import GuardContext


def test_guard_result_ok_only_for_continue():
    cont = GuardResult("G", "stage", Decision.CONTINUE)
    stop = GuardResult("G", "stage", Decision.STOP, next_action=NextAction.ASK_USER)
    assert cont.ok is True
    assert stop.ok is False


def test_guard_result_defaults():
    r = GuardResult("G", "stage", Decision.CONTINUE)
    assert r.next_action is NextAction.NONE
    assert r.reason is None
    assert r.payload_hash is None
    assert r.input_refs == {}
    assert r.normalizations == []


def test_guard_result_is_frozen():
    r = GuardResult("G", "stage", Decision.CONTINUE)
    with pytest.raises(dataclasses.FrozenInstanceError):
        r.reason = "x"


def test_guard_context_defaults_are_empty():
    ctx = GuardContext()
    assert ctx.application is None
    assert ctx.approval is None
    assert ctx.resume_artifact is None
    assert ctx.disclosed_resume_hash is None
    assert ctx.summary_artifacts == []
    assert ctx.browser_state is None
    assert ctx.now is None
    assert ctx.trace_id is None


def test_guard_context_accepts_state():
    ctx = GuardContext(application={"application_id": "a1"}, disclosed_resume_hash="h")
    assert ctx.application["application_id"] == "a1"
    assert ctx.disclosed_resume_hash == "h"


def test_guard_context_is_frozen():
    ctx = GuardContext()
    with pytest.raises(dataclasses.FrozenInstanceError):
        ctx.trace_id = "x"
