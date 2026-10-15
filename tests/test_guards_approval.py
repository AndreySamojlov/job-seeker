from datetime import datetime, timedelta, timezone

from job_machine.guards.base import Decision, NextAction
from job_machine.guards.context import GuardContext
from job_machine.guards import approval


T0 = datetime(2026, 6, 22, 12, 0, tzinfo=timezone.utc)


def _approved_ctx(**over):
    ctx = dict(
        application={"application_id": "a1", "payload_hash": "PH"},
        approval={
            "approval_status": "approved",
            "approval_token": "tok",
            "payload_hash": "PH",
            "expires_at": T0 + timedelta(hours=1),
        },
        resume_artifact={"content_hash": "RH"},
        disclosed_resume_hash="RH",
        summary_artifacts=[{"artifact_type": "approval_summary"}],
        now=T0,
    )
    ctx.update(over)
    return GuardContext(**ctx)


def test_no_submit_without_approval_continue():
    r = approval.NoSubmitWithoutApproval().check(_approved_ctx())
    assert r.decision is Decision.CONTINUE


def test_no_submit_without_approval_stop_when_pending():
    ctx = _approved_ctx(approval={"approval_status": "pending", "approval_token": ""})
    r = approval.NoSubmitWithoutApproval().check(ctx)
    assert r.decision is Decision.STOP
    assert r.next_action is NextAction.ASK_USER
    assert r.input_refs.get("application_id") == "a1"


def test_no_submit_without_approval_stop_when_missing():
    r = approval.NoSubmitWithoutApproval().check(_approved_ctx(approval=None))
    assert r.decision is Decision.STOP


def test_payload_hash_match_continue():
    r = approval.NoSubmitIfPayloadHashChanged().check(_approved_ctx())
    assert r.decision is Decision.CONTINUE
    assert r.payload_hash == "PH"


def test_payload_hash_mismatch_stop():
    ctx = _approved_ctx(application={"application_id": "a1", "payload_hash": "OTHER"})
    r = approval.NoSubmitIfPayloadHashChanged().check(ctx)
    assert r.decision is Decision.STOP
    assert r.next_action is NextAction.MANUAL_REVIEW


def test_expiry_continue_when_future():
    r = approval.NoSubmitAfterApprovalExpiry().check(_approved_ctx())
    assert r.decision is Decision.CONTINUE


def test_expiry_stop_when_past():
    ctx = _approved_ctx(
        approval={
            "approval_status": "approved",
            "approval_token": "tok",
            "payload_hash": "PH",
            "expires_at": T0 - timedelta(seconds=1),
        }
    )
    r = approval.NoSubmitAfterApprovalExpiry().check(ctx)
    assert r.decision is Decision.STOP
    assert r.next_action is NextAction.ASK_USER


def test_expiry_stop_when_now_missing():
    ctx = _approved_ctx(now=None)
    r = approval.NoSubmitAfterApprovalExpiry().check(ctx)
    assert r.decision is Decision.STOP
    assert r.next_action is NextAction.ESCALATE_TO_DEBUG


def test_disclosed_summary_continue():
    r = approval.NoFillBeforeDisclosedSummary().check(_approved_ctx())
    assert r.decision is Decision.CONTINUE


def test_disclosed_summary_stop_when_absent():
    r = approval.NoFillBeforeDisclosedSummary().check(_approved_ctx(summary_artifacts=[]))
    assert r.decision is Decision.STOP
    assert r.next_action is NextAction.MANUAL_REVIEW


def test_resume_hash_match_continue():
    r = approval.NoResumeUploadWithoutHashMatch().check(_approved_ctx())
    assert r.decision is Decision.CONTINUE


def test_resume_hash_mismatch_stop():
    ctx = _approved_ctx(resume_artifact={"content_hash": "WRONG"})
    r = approval.NoResumeUploadWithoutHashMatch().check(ctx)
    assert r.decision is Decision.STOP
    assert r.next_action is NextAction.MANUAL_REVIEW


# --- fail-closed регрессии (falsy-равенство не должно давать CONTINUE) ---

def test_payload_hash_both_empty_stops():
    ctx = _approved_ctx(
        application={"application_id": "a1", "payload_hash": ""},
        approval={
            "approval_status": "approved", "approval_token": "tok",
            "payload_hash": "", "expires_at": T0 + timedelta(hours=1),
        },
    )
    assert approval.NoSubmitIfPayloadHashChanged().check(ctx).decision is Decision.STOP


def test_expiry_stop_when_equal_now():
    ctx = _approved_ctx(
        approval={
            "approval_status": "approved", "approval_token": "tok",
            "payload_hash": "PH", "expires_at": T0,
        },
    )
    assert approval.NoSubmitAfterApprovalExpiry().check(ctx).decision is Decision.STOP


def test_resume_hash_both_empty_stops():
    ctx = _approved_ctx(resume_artifact={"content_hash": ""}, disclosed_resume_hash="")
    assert approval.NoResumeUploadWithoutHashMatch().check(ctx).decision is Decision.STOP


def test_disclosed_summary_ignores_none_element():
    ctx = _approved_ctx(summary_artifacts=[None, {"artifact_type": "approval_summary"}])
    assert approval.NoFillBeforeDisclosedSummary().check(ctx).decision is Decision.CONTINUE


def test_disclosed_summary_none_element_only_stops():
    ctx = _approved_ctx(summary_artifacts=[None])
    assert approval.NoFillBeforeDisclosedSummary().check(ctx).decision is Decision.STOP


def test_expiry_tz_mismatch_stops_escalate():
    # tz-naive expires_at против tz-aware ctx.now (T0) — сравнение бросило бы TypeError;
    # guard ловит и закрывается чистым STOP, не роняя submit-путь.
    naive_expires = datetime(2026, 6, 22, 13, 0)  # без tzinfo
    ctx = _approved_ctx(
        approval={
            "approval_status": "approved", "approval_token": "tok",
            "payload_hash": "PH", "expires_at": naive_expires,
        },
    )
    r = approval.NoSubmitAfterApprovalExpiry().check(ctx)
    assert r.decision is Decision.STOP
    assert r.next_action is NextAction.ESCALATE_TO_DEBUG
