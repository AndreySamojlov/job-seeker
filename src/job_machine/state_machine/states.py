from enum import Enum


class VacancyState(Enum):
    RAW_LEAD = "raw_lead"
    DISCOVERED = "discovered"
    VERIFIED = "verified"
    TRIAGED = "triaged"
    SKIPPED = "skipped"


class ApplicationState(Enum):
    NEEDS_PACKAGE = "needs_package"
    PACKAGE_READY = "package_ready"
    FORM_INSPECTED = "form_inspected"
    FILL_BLOCKED = "fill_blocked"
    PRE_SUBMIT_READY = "pre_submit_ready"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    SUBMIT_BLOCKED = "submit_blocked"
    SUBMITTED = "submitted"
    CONFIRMED = "confirmed"
    FAILED = "failed"
