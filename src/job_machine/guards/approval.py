from job_machine.guards.base import Decision, Guard, GuardResult, NextAction
from job_machine.guards import registry

FILL_STAGE = "fill"
SUBMIT_STAGE = "submit"


def _app_id(ctx) -> str | None:
    return (ctx.application or {}).get("application_id")


def _refs(ctx) -> dict:
    return {"application_id": _app_id(ctx)}


class NoSubmitWithoutApproval(Guard):
    """[SAFETY] Submit только при approval_status='approved'.

    Проверка наличия approval_token — дешёвый integrity-инвариант (у approved-записи
    он всегда есть), НЕ аутентификация: токен не secret-capability (см. CLAUDE.md §3).
    """
    name = "NoSubmitWithoutApproval"
    stage = SUBMIT_STAGE

    def check(self, ctx) -> GuardResult:
        appr = ctx.approval or {}
        if appr.get("approval_status") == "approved" and appr.get("approval_token"):
            return GuardResult(self.name, self.stage, Decision.CONTINUE,
                               payload_hash=appr.get("payload_hash"))
        return GuardResult(
            self.name, self.stage, Decision.STOP,
            next_action=NextAction.ASK_USER,
            reason="no approved approval token for application",
            input_refs=_refs(ctx),
        )


class NoSubmitIfPayloadHashChanged(Guard):
    name = "NoSubmitIfPayloadHashChanged"
    stage = SUBMIT_STAGE

    def check(self, ctx) -> GuardResult:
        app_h = (ctx.application or {}).get("payload_hash")
        appr_h = (ctx.approval or {}).get("payload_hash")
        if app_h and appr_h and app_h == appr_h:
            return GuardResult(self.name, self.stage, Decision.CONTINUE, payload_hash=app_h)
        return GuardResult(
            self.name, self.stage, Decision.STOP,
            next_action=NextAction.MANUAL_REVIEW,
            reason=f"payload hash mismatch: application={app_h} approval={appr_h}",
            payload_hash=app_h, input_refs=_refs(ctx),
        )


class NoSubmitAfterApprovalExpiry(Guard):
    name = "NoSubmitAfterApprovalExpiry"
    stage = SUBMIT_STAGE

    def check(self, ctx) -> GuardResult:
        if ctx.now is None:
            return GuardResult(
                self.name, self.stage, Decision.STOP,
                next_action=NextAction.ESCALATE_TO_DEBUG,
                reason="ctx.now missing — cannot evaluate expiry",
                input_refs=_refs(ctx),
            )
        expires_at = (ctx.approval or {}).get("expires_at")
        try:
            not_expired = expires_at is not None and expires_at > ctx.now
        except TypeError:
            # tz-naive vs tz-aware (или иной несопоставимый тип) — не падаем на
            # submit-гейте, а закрываемся: чистый STOP вместо непойманного исключения,
            # чтобы сохранить гарантию audit-события на блоке (спека §7).
            return GuardResult(
                self.name, self.stage, Decision.STOP,
                next_action=NextAction.ESCALATE_TO_DEBUG,
                reason="expires_at/now datetime mismatch — cannot evaluate expiry",
                input_refs=_refs(ctx),
            )
        if not_expired:
            return GuardResult(self.name, self.stage, Decision.CONTINUE)
        return GuardResult(
            self.name, self.stage, Decision.STOP,
            next_action=NextAction.ASK_USER,
            reason="approval expired or missing expires_at",
            input_refs=_refs(ctx),
        )


class NoFillBeforeDisclosedSummary(Guard):
    name = "NoFillBeforeDisclosedSummary"
    stage = FILL_STAGE

    def check(self, ctx) -> GuardResult:
        has_summary = any(
            isinstance(a, dict) and a.get("artifact_type") == "approval_summary"
            for a in (ctx.summary_artifacts or [])
        )
        if has_summary:
            return GuardResult(self.name, self.stage, Decision.CONTINUE)
        return GuardResult(
            self.name, self.stage, Decision.STOP,
            next_action=NextAction.MANUAL_REVIEW,
            reason="no disclosed approval_summary artifact before fill",
            input_refs=_refs(ctx),
        )


class NoResumeUploadWithoutHashMatch(Guard):
    name = "NoResumeUploadWithoutHashMatch"
    stage = FILL_STAGE

    def check(self, ctx) -> GuardResult:
        actual = (ctx.resume_artifact or {}).get("content_hash")
        disclosed = ctx.disclosed_resume_hash
        if actual and disclosed and actual == disclosed:
            return GuardResult(self.name, self.stage, Decision.CONTINUE)
        return GuardResult(
            self.name, self.stage, Decision.STOP,
            next_action=NextAction.MANUAL_REVIEW,
            reason=f"resume hash mismatch: artifact={actual} disclosed={disclosed}",
            input_refs=_refs(ctx),
        )


def register_all(reg=registry.DEFAULT) -> None:
    for guard in (
        NoSubmitWithoutApproval(),
        NoSubmitIfPayloadHashChanged(),
        NoSubmitAfterApprovalExpiry(),
        NoFillBeforeDisclosedSummary(),
        NoResumeUploadWithoutHashMatch(),
    ):
        reg.register(guard)
