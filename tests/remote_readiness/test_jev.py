import json

import httpx
import pytest

from job_machine.remote_readiness.jev import evaluate_payload
from job_machine.remote_readiness.models import ReadinessError


def payload():
    return {"model": "jev-1.13.0", "state": {"job_text": "synthetic", "rubric_version": "rwr-1"},
            "questions": {"remote_work_readiness": {"type": "noul", "instructions": "test"}}}


@pytest.mark.parametrize("value", [0, 1, 0.12345678912345678])
def test_fraction_preserved_and_one_bearer_post(value):
    requests = []
    def transport(request):
        requests.append(request)
        assert str(request.url) == "https://api.typesafe.ai/v1/systemone"
        assert request.method == "POST"
        assert request.headers["authorization"] == "Bearer synthetic-key"
        assert json.loads(request.content) == payload()
        assert "synthetic-key" not in str(request.url) + request.content.decode()
        return httpx.Response(200, json={"model": "jev-1.13.0", "answers": {
            "remote_work_readiness": {"type": "noul", "noul": value}}})
    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        answer = evaluate_payload(payload(), client=client, api_key="synthetic-key")
    assert len(requests) == 1
    assert answer.value == value
    assert (answer.model, answer.rubric_version) == ("jev-1.13.0", "rwr-1")


def test_configured_request_timeout_is_applied_to_jev_request():
    requests = []
    def transport(request):
        requests.append(request)
        return httpx.Response(200, json={"model": "jev-1.13.0", "answers": {
            "remote_work_readiness": {"type": "noul", "noul": 0.5}}})
    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        evaluate_payload(payload(), client=client, api_key="key", timeout_seconds=47)
    assert requests[0].extensions["timeout"]["read"] == 47


@pytest.mark.parametrize("value", [True, False, float("nan"), float("inf"), -float("inf"), -0.01, 1.01, "0.5", None])
def test_invalid_noul_is_error_not_zero(value, caplog):
    body = {"model": "jev-1.13.0", "answers": {"remote_work_readiness": {"type": "noul", "noul": value}}, "secret": "raw-sensitive"}
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, content=json.dumps(body)))) as client:
        with pytest.raises(ReadinessError, match="^invalid_response$"):
            evaluate_payload(payload(), client=client, api_key="synthetic-key")
    assert "raw-sensitive" not in caplog.text


@pytest.mark.parametrize("body", [[], {}, {"model": "jev-latest"},
    {"model": "jev-1.13.0", "answers": {"remote_work_readiness": {"type": "score", "noul": 0.5}}}])
def test_malformed_response_rejected(body):
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body))) as client:
        with pytest.raises(ReadinessError, match="invalid_response"):
            evaluate_payload(payload(), client=client, api_key="key")


@pytest.mark.parametrize("status,retryable", [(401, False), (429, True), (500, True)])
def test_http_errors_sanitized(status, retryable):
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(status, text="sensitive"))) as client:
        with pytest.raises(ReadinessError) as error:
            evaluate_payload(payload(), client=client, api_key="key")
    assert str(error.value) == f"http_{status}"
    assert error.value.retryable is retryable


def test_network_error_sanitized():
    def fail(request):
        raise httpx.ConnectError("sensitive", request=request)
    with httpx.Client(transport=httpx.MockTransport(fail)) as client:
        with pytest.raises(ReadinessError, match="^network_error$") as error:
            evaluate_payload(payload(), client=client, api_key="key")
    assert error.value.retryable


def test_non_json_response_sanitized(caplog):
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, text="raw-sensitive"))) as client:
        with pytest.raises(ReadinessError, match="^invalid_response$"):
            evaluate_payload(payload(), client=client, api_key="key")
    assert "raw-sensitive" not in caplog.text


@pytest.mark.parametrize("mutation", ["candidate", "model", "rubric", "key", "extra"])
def test_invalid_snapshot_fails_before_http(mutation):
    request_payload = payload()
    if mutation == "candidate":
        request_payload["state"]["facts"] = ["candidate secret"]
    elif mutation == "model":
        request_payload["model"] = "jev-latest"
    elif mutation == "rubric":
        request_payload["state"]["rubric_version"] = "rwr-2"
    elif mutation == "extra":
        request_payload["candidate"] = "secret"
    def unexpected(_):
        pytest.fail("invalid snapshot made an HTTP request")
    with httpx.Client(transport=httpx.MockTransport(unexpected)) as client:
        with pytest.raises(ReadinessError):
            evaluate_payload(request_payload, client=client, api_key="" if mutation == "key" else "key")
