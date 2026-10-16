import json
from uuid import UUID

import httpx
import pytest

from job_machine.fit.jev import evaluate_payload
from job_machine.fit.models import FitError, FitFact, FitInput
from job_machine.fit.rubric import build_payload


def payload():
    return build_payload(FitInput("synthetic", UUID(int=1), "private vacancy", (FitFact("f1", "private fact", "verified", "fixture"),)))


def response(raw=3, choice="no_confirmed_violation", model="jev-1.13.0"):
    return {"model": model, "answers": {"fit_score": {"type": "score", "score": raw, "confidence": 1, "legend": {}, "probabilities": {}}, "mandatory_requirement": {"type": "choice", "choice": choice, "confidence": 1, "probabilities": {}}}, "usage": {"input_tokens": 1, "output_tokens": 1}}


def evaluate(body):
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=body))) as client:
        return evaluate_payload(payload(), client=client, api_key="synthetic-token")


@pytest.mark.parametrize("raw,want", [(0,0),(1,25),(2,50),(3,75),(4,100),(2.5,63)])
def test_score_normalization(raw, want):
    assert evaluate(response(raw)).score == want


@pytest.mark.parametrize("choice,want", [("confirmed_violation",0),("unknown",75)])
def test_mandatory_override_only_for_confirmed(choice,want):
    assert evaluate(response(choice=choice)).score == want


@pytest.mark.parametrize("raw", [True, float("nan"), float("inf"), -1,5,"3",None])
def test_invalid_raw_blocked(raw):
    body=json.dumps(response(raw))
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=body))) as client:
        with pytest.raises(FitError) as exc:
            evaluate_payload(payload(),client=client,api_key="synthetic-token")
    assert not exc.value.retryable


@pytest.mark.parametrize("mutation", ["model","missing_choice","choice","score_type","choice_type","not_dict"])
def test_invalid_response_blocked(mutation):
    body=response()
    if mutation=="model": body["model"]="jev-latest"
    elif mutation=="missing_choice": del body["answers"]["mandatory_requirement"]
    elif mutation=="choice": body["answers"]["mandatory_requirement"]["choice"]="yes"
    elif mutation=="score_type": body["answers"]["fit_score"]["type"]="noul"
    elif mutation=="choice_type": body["answers"]["mandatory_requirement"]["type"]="noul"
    else: body=[]
    with pytest.raises(FitError) as exc: evaluate(body)
    assert not exc.value.retryable


def test_single_http_request_contract():
    calls=[]
    def handler(request):
        calls.append(request)
        assert str(request.url)=="https://api.typesafe.ai/v1/systemone"
        assert request.headers["authorization"]=="Bearer synthetic-token"
        assert "synthetic-token" not in request.content.decode()
        assert request.extensions["timeout"]["read"]==30
        return httpx.Response(200,json=response())
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result=evaluate_payload(payload(),client=client,api_key="synthetic-token")
    assert len(calls)==1
    assert (result.model,result.rubric_version)==("jev-1.13.0","jfit-1")


@pytest.mark.parametrize("status,retryable", [(429,True),(503,True),(401,False),(422,False)])
def test_http_error_sanitized(status,retryable,caplog):
    calls=[]
    def handler(request):
        calls.append(request)
        return httpx.Response(status,text="synthetic-token private fact",headers={"Retry-After":"2"})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(FitError) as exc: evaluate_payload(payload(),client=client,api_key="synthetic-token")
    assert len(calls)==1
    assert exc.value.retryable is retryable
    assert exc.value.retry_after_seconds==(2 if retryable else None)
    assert "synthetic-token" not in str(exc.value)+caplog.text
    assert "private fact" not in str(exc.value)+caplog.text


@pytest.mark.parametrize("value", ["-1","NaN","inf","junk"])
def test_invalid_retry_after_ignored(value):
    with httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(429,headers={"Retry-After":value}))) as client:
        with pytest.raises(FitError) as exc: evaluate_payload(payload(),client=client,api_key="x")
    assert exc.value.retry_after_seconds is None


@pytest.mark.parametrize("error", [httpx.ReadTimeout,httpx.ConnectError])
def test_network_errors_retryable_sanitized(error):
    def handler(request): raise error("synthetic-token private fact",request=request)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(FitError) as exc: evaluate_payload(payload(),client=client,api_key="x")
    assert exc.value.retryable
    assert "private fact" not in str(exc.value)
    assert exc.value.__cause__ is None


def test_malformed_json_is_blocked_without_body(caplog):
    with httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(200,content="private fact synthetic-token"))) as client:
        with pytest.raises(FitError) as exc: evaluate_payload(payload(),client=client,api_key="synthetic-token")
    assert exc.value.code=="invalid_response"
    assert not exc.value.retryable
    assert "private fact" not in str(exc.value)+caplog.text


def test_oversized_saved_payload_never_reaches_network():
    body=payload()
    body["state"]["job_text"]="я"*100000
    def handler(request): pytest.fail("oversized payload was sent")
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(FitError) as exc: evaluate_payload(body,client=client,api_key="x")
    assert exc.value.code=="input_too_large"


def test_http_date_retry_after_is_respected():
    from datetime import datetime, timedelta, timezone
    from email.utils import format_datetime
    future=format_datetime(datetime.now(timezone.utc)+timedelta(seconds=60),usegmt=True)
    with httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(429,headers={"Retry-After":future}))) as client:
        with pytest.raises(FitError) as exc: evaluate_payload(payload(),client=client,api_key="x")
    assert 58 <= exc.value.retry_after_seconds <= 60
