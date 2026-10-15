import importlib

from job_machine.guards import registry


def test_default_registry_has_safety_critical_guards():
    # Импорт пакета триггерит регистрацию.
    import job_machine.guards  # noqa: F401
    importlib.reload(importlib.import_module("job_machine.guards"))
    names = set(registry.all_guards())
    assert {
        "NoSubmitWithoutApproval",
        "NoSubmitIfPayloadHashChanged",
        "NoSubmitAfterApprovalExpiry",
        "NoFillBeforeDisclosedSummary",
        "NoResumeUploadWithoutHashMatch",
        "BrowserBlockerDetector",
    } <= names


def test_slot_modules_register_nothing():
    import job_machine.guards.honesty as honesty
    import job_machine.guards.cost as cost
    # Слоты не имеют guard-классов и не регистрируют ничего (фейк-CONTINUE запрещён).
    assert not [n for n in dir(honesty) if n[0].isupper() and n != "Guard"]
    assert not [n for n in dir(cost) if n[0].isupper() and n != "Guard"]
