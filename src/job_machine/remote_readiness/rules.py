"""Consumer configuration and passthrough through the public Engine API."""
from cockpit_engine.rules import invoke_external_decision, load_external_decision

READINESS_CODE = "remote_work_readiness"
READINESS_CATALOG = {"external_decisions": {READINESS_CODE: {
    "enabled": True, "handler": "jev", "version": "rwr-1",
    "config": {"model": "jev-1.13.0", "rubric_version": "rwr-1"},
}}}


def invoke_readiness(state, config, handlers):
    decision = load_external_decision(config, READINESS_CODE)
    return invoke_external_decision(decision, state, handlers=handlers)
