from job_machine.state_machine.states import ApplicationState as A
from job_machine.state_machine.states import VacancyState as V

# (entity_type, from_state) -> множество разрешённых to_state.
# Отсутствие ключа = терминальное состояние (нет исходящих переходов):
# CONFIRMED/FAILED/SKIPPED намеренно без entry — attempt_transition из них вернёт
# illegal-transition. Не добавлять им entry без явной необходимости.
ALLOWED = {
    ("application", A.NEEDS_PACKAGE): {A.PACKAGE_READY, A.FAILED},
    ("application", A.PACKAGE_READY): {A.FORM_INSPECTED, A.NEEDS_PACKAGE, A.FAILED},
    ("application", A.FORM_INSPECTED): {A.PRE_SUBMIT_READY, A.FILL_BLOCKED, A.FAILED},
    ("application", A.FILL_BLOCKED): {A.FORM_INSPECTED, A.NEEDS_PACKAGE, A.FAILED},
    ("application", A.PRE_SUBMIT_READY): {A.AWAITING_APPROVAL, A.FAILED},
    ("application", A.AWAITING_APPROVAL): {A.APPROVED, A.FAILED},
    ("application", A.APPROVED): {A.SUBMITTED, A.FAILED},
    ("application", A.SUBMIT_BLOCKED): {A.NEEDS_PACKAGE, A.FAILED},
    ("application", A.SUBMITTED): {A.CONFIRMED, A.FAILED},
    ("vacancy", V.RAW_LEAD): {V.DISCOVERED, V.SKIPPED},
    ("vacancy", V.DISCOVERED): {V.VERIFIED, V.SKIPPED},
    ("vacancy", V.VERIFIED): {V.TRIAGED, V.SKIPPED},
    ("vacancy", V.TRIAGED): {V.SKIPPED},
}

# (entity_type, from_state, to_state) -> список имён guards (порядок = порядок прогона).
GUARDS = {
    ("application", A.FORM_INSPECTED, A.PRE_SUBMIT_READY): [
        "NoFillBeforeDisclosedSummary",
        "NoResumeUploadWithoutHashMatch",
        "BrowserBlockerDetector",
    ],
    # Многослойная защита: на момент перехода в APPROVED проверяем срок и совпадение
    # payload_hash. Сильнейшие проверки (включая NoSubmitWithoutApproval и resume-hash)
    # стоят на необратимом APPROVED -> SUBMITTED ниже — submit перепроверяется целиком,
    # даже если APPROVED достигнут. Не ослаблять submit-гейт ради этого перехода.
    ("application", A.AWAITING_APPROVAL, A.APPROVED): [
        "NoSubmitAfterApprovalExpiry",
        "NoSubmitIfPayloadHashChanged",
    ],
    ("application", A.APPROVED, A.SUBMITTED): [
        "NoSubmitWithoutApproval",
        "NoSubmitIfPayloadHashChanged",
        "NoSubmitAfterApprovalExpiry",
        "NoResumeUploadWithoutHashMatch",
    ],
}
