import pytest

from job_machine.guards.base import Decision, Guard, GuardResult
from job_machine.guards import registry


class _Dummy(Guard):
    name = "Dummy"
    stage = "test"

    def check(self, ctx):
        return GuardResult(self.name, self.stage, Decision.CONTINUE)


def test_register_and_get():
    reg = registry.Registry()
    g = _Dummy()
    reg.register(g)
    assert reg.get("Dummy") is g
    assert "Dummy" in reg.all_guards()


def test_register_duplicate_raises():
    reg = registry.Registry()
    reg.register(_Dummy())
    with pytest.raises(ValueError):
        reg.register(_Dummy())


def test_get_unknown_raises():
    reg = registry.Registry()
    with pytest.raises(KeyError):
        reg.get("Nope")


def test_all_guards_returns_copy():
    reg = registry.Registry()
    reg.register(_Dummy())
    snapshot = reg.all_guards()
    snapshot["injected"] = object()
    assert "injected" not in reg.all_guards()
