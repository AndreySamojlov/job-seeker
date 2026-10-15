"""Контур guards: детерминированные политики как исполняемый код.

Импорт пакета регистрирует все живые guards в registry.DEFAULT.
"""
from job_machine.guards import approval, browser, registry


def _register_defaults() -> None:
    """Идемпотентно регистрирует живые guards в DEFAULT (безопасно при reload)."""
    existing = set(registry.all_guards())
    if not {
        "NoSubmitWithoutApproval",
        "BrowserBlockerDetector",
    } <= existing:
        approval.register_all()
        browser.register_all()


_register_defaults()
