import json

import httpx
import pytest

from job_machine.mail.models import ApplicationRef, EmailInput
from job_machine.pipeline.llm import DeepSeekClient, LLMResponseError


def _fake_http(response_content: str) -> httpx.Client:
    def handler(request):
        body = {
            "choices": [{"message": {"content": response_content}}],
        }
        return httpx.Response(200, json=body)
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_classify_reply_parses_valid_json():
    content = json.dumps({
        "application_id": "11111111-1111-1111-1111-111111111111",
        "candidate_id": "andrey-s",
        "category": "rejected",
        "confidence": 0.95,
    })
    client = DeepSeekClient("k", http=_fake_http(content))
    email = EmailInput(uid=1, from_addr="hr@acme.com", subject="Update",
                        body="Unfortunately we are moving forward with other candidates.")
    apps = [ApplicationRef(application_id="11111111-1111-1111-1111-111111111111",
                            candidate_id="andrey-s", company="Acme", role="QA Lead")]
    result = client.classify_reply(email, apps)
    assert result.category == "rejected"
    assert result.confidence == 0.95


def test_classify_reply_raises_on_invalid_json():
    client = DeepSeekClient("k", http=_fake_http("not json"))
    email = EmailInput(uid=1, from_addr="hr@acme.com", subject="Update", body="...")
    with pytest.raises(LLMResponseError):
        client.classify_reply(email, [])
