"""Unit-only shim until Task 5 supplies the new immutable Engine wheel."""
import copy
import importlib
import sys
from types import SimpleNamespace

import cockpit_engine.rules
import httpx
import pytest


@pytest.fixture
def rules(monkeypatch):
    def load(catalog, code):
        entry = catalog["external_decisions"][code]
        if entry["enabled"] is not True:
            raise ValueError("disabled")
        return SimpleNamespace(code=code, **{k: entry[k] for k in ("handler", "version", "config")})
    def invoke(decision, state, *, handlers):
        return handlers[decision.handler](decision, state)
    monkeypatch.setattr(cockpit_engine.rules, "load_external_decision", load, raising=False)
    monkeypatch.setattr(cockpit_engine.rules, "invoke_external_decision", invoke, raising=False)
    name = "job_machine.remote_readiness.rules"
    sys.modules.pop(name, None)
    module = importlib.import_module(name)
    yield module
    sys.modules.pop(name, None)


def test_rules_preserves_identity_and_inputs(rules):
    state = {"synthetic": [1, 2]}
    config = copy.deepcopy(rules.READINESS_CATALOG)
    original = copy.deepcopy((state, config))
    sentinel = object()
    calls = []
    def handler(decision, actual):
        assert actual is state
        assert decision.handler == "jev"
        calls.append(decision)
        return sentinel
    assert rules.invoke_readiness(state, config, {"jev": handler}) is sentinel
    assert len(calls) == 1
    assert (state, config) == original


def test_bound_handler_uses_saved_payload(rules):
    from job_machine.remote_readiness.jev import make_jev_handler
    from job_machine.remote_readiness.rubric import build_payload
    decision = cockpit_engine.rules.load_external_decision(rules.READINESS_CATALOG, rules.READINESS_CODE)
    payload = build_payload("Synthetic worldwide remote advertisement", decision=decision)
    original = copy.deepcopy(payload)
    def transport(request):
        import json
        assert json.loads(request.content) == original
        return httpx.Response(200, json={"model": "jev-1.13.0", "answers": {
            "remote_work_readiness": {"type": "noul", "noul": 0.867530912345}}})
    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        handler = make_jev_handler(client=client, api_key="synthetic-key")
        answer = rules.invoke_readiness(payload, rules.READINESS_CATALOG, {"jev": handler})
    assert answer.value == 0.867530912345
    assert payload == original


def test_bound_handler_rejects_changed_rubric_before_http(rules):
    from job_machine.remote_readiness.jev import make_jev_handler
    from job_machine.remote_readiness.models import ReadinessError
    config = copy.deepcopy(rules.READINESS_CATALOG)
    config["external_decisions"][rules.READINESS_CODE]["version"] = "rwr-2"
    def unexpected(_):
        pytest.fail("changed rubric reached provider")
    with httpx.Client(transport=httpx.MockTransport(unexpected)) as client:
        with pytest.raises(ReadinessError, match="unsupported_readiness_configuration"):
            rules.invoke_readiness({}, config, {"jev": make_jev_handler(client=client, api_key="key")})
