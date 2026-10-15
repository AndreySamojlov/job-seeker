from job_machine.state_machine.states import VacancyState, ApplicationState


def test_application_states_have_string_values():
    assert ApplicationState.NEEDS_PACKAGE.value == "needs_package"
    assert ApplicationState.SUBMITTED.value == "submitted"
    assert ApplicationState.CONFIRMED.value == "confirmed"
    assert ApplicationState.FAILED.value == "failed"


def test_vacancy_states_have_string_values():
    assert VacancyState.RAW_LEAD.value == "raw_lead"
    assert VacancyState.TRIAGED.value == "triaged"


from job_machine.state_machine import transitions
from job_machine.state_machine.states import ApplicationState as A


def test_allowed_contains_submit_path():
    assert A.SUBMITTED in transitions.ALLOWED[("application", A.APPROVED)]
    assert A.PRE_SUBMIT_READY in transitions.ALLOWED[("application", A.FORM_INSPECTED)]


def test_submit_transition_has_all_submit_guards():
    guards = transitions.GUARDS[("application", A.APPROVED, A.SUBMITTED)]
    assert guards == [
        "NoSubmitWithoutApproval",
        "NoSubmitIfPayloadHashChanged",
        "NoSubmitAfterApprovalExpiry",
        "NoResumeUploadWithoutHashMatch",
    ]


def test_fill_transition_has_blocker_and_summary_guards():
    guards = transitions.GUARDS[("application", A.FORM_INSPECTED, A.PRE_SUBMIT_READY)]
    assert "NoFillBeforeDisclosedSummary" in guards
    assert "NoResumeUploadWithoutHashMatch" in guards
    assert "BrowserBlockerDetector" in guards


from job_machine.state_machine import controller
from job_machine.state_machine.states import ApplicationState as A
from job_machine.guards.base import Decision, GuardResult, NextAction
from job_machine.guards.context import GuardContext


class _Recorder:
    def __init__(self):
        self.state_calls = []
        self.audit_calls = []

    def state_writer(self, entity_type, entity_id, *, state=None, current_blocker="__keep__"):
        self.state_calls.append((entity_type, entity_id, state, current_blocker))

    def audit_emitter(self, entity_type, entity_id, event_type, payload, trace_id=None):
        self.audit_calls.append((entity_type, entity_id, event_type, payload))


def _pass_guard(name):
    class _G:
        def check(self, ctx):
            return GuardResult(name, "s", Decision.CONTINUE)
    return _G()


def _stop_guard(name):
    class _G:
        def check(self, ctx):
            return GuardResult(name, "s", Decision.STOP,
                               next_action=NextAction.ASK_USER, reason="blocked")
    return _G()


def test_illegal_transition_blocks_and_audits():
    rec = _Recorder()
    res = controller.attempt_transition(
        "application", "a1", A.NEEDS_PACKAGE, A.SUBMITTED, GuardContext(),
        state_writer=rec.state_writer, audit_emitter=rec.audit_emitter,
        guard_resolver=_pass_guard,
    )
    assert res.ok is False
    assert res.blocked_by.reason.startswith("illegal transition")
    # illegal-transition не дёргает state_writer вовсе (даже current_blocker)
    assert rec.state_calls == []
    assert rec.audit_calls and rec.audit_calls[0][2].startswith("guard.")


def test_blocked_by_guard_does_not_change_state():
    rec = _Recorder()
    res = controller.attempt_transition(
        "application", "a1", A.APPROVED, A.SUBMITTED, GuardContext(),
        state_writer=rec.state_writer, audit_emitter=rec.audit_emitter,
        guard_resolver=_stop_guard,
    )
    assert res.ok is False
    assert res.blocked_by.guard_name == "NoSubmitWithoutApproval"
    # current_blocker выставлен, state=target не записан
    assert rec.state_calls == [("application", "a1", None, "blocked")]
    assert rec.audit_calls[0][2] == "guard.NoSubmitWithoutApproval"


def test_all_guards_pass_commits_state_and_audits_transition():
    rec = _Recorder()
    res = controller.attempt_transition(
        "application", "a1", A.APPROVED, A.SUBMITTED, GuardContext(),
        state_writer=rec.state_writer, audit_emitter=rec.audit_emitter,
        guard_resolver=_pass_guard,
    )
    assert res.ok is True
    assert ("application", "a1", A.SUBMITTED, None) in rec.state_calls
    assert rec.audit_calls[-1][2] == "state.approved__submitted"


def test_transition_without_guards_just_commits():
    rec = _Recorder()
    res = controller.attempt_transition(
        "application", "a1", A.NEEDS_PACKAGE, A.PACKAGE_READY, GuardContext(),
        state_writer=rec.state_writer, audit_emitter=rec.audit_emitter,
        guard_resolver=_pass_guard,
    )
    assert res.ok is True
    assert ("application", "a1", A.PACKAGE_READY, None) in rec.state_calls
