from job_machine.state_machine.controller import attempt_transition
from job_machine.state_machine.states import ApplicationState as A


def _writers():
    calls = {}
    def sw(et, eid, *, state=None, current_blocker=None):
        calls["state"] = state; calls["blocker"] = current_blocker
    def ae(et, eid, ev, payload, trace_id=None):
        calls.setdefault("events", []).append(ev)
    return sw, ae, calls


def test_fill_blocked_can_reopen_to_needs_package():
    sw, ae, calls = _writers()
    res = attempt_transition("application", "a1", A.FILL_BLOCKED, A.NEEDS_PACKAGE, None,
                             state_writer=sw, audit_emitter=ae)
    assert res.ok is True
    assert calls["state"] == A.NEEDS_PACKAGE


def test_package_ready_can_reopen_to_needs_package():
    sw, ae, calls = _writers()
    res = attempt_transition("application", "a1", A.PACKAGE_READY, A.NEEDS_PACKAGE, None,
                             state_writer=sw, audit_emitter=ae)
    assert res.ok is True


def test_existing_targets_still_legal():
    sw, ae, _ = _writers()
    assert attempt_transition("application", "a1", A.FILL_BLOCKED, A.FORM_INSPECTED, None,
                              state_writer=sw, audit_emitter=ae).ok is True


def test_submitted_cannot_reopen():
    sw, ae, _ = _writers()
    res = attempt_transition("application", "a1", A.SUBMITTED, A.NEEDS_PACKAGE, None,
                             state_writer=sw, audit_emitter=ae)
    assert res.ok is False
