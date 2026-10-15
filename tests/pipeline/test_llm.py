"""Тесты LLM-клиента: triage verdict, resume phrasing, client_from_env."""
import json

import httpx
import pytest

from job_machine.pipeline.llm import (
    DeepSeekClient,
    LLMResponseError,
    client_from_env,
)
from job_machine.resume.models import PhrasingRequest
from job_machine.triage.models import ClaimRecord, TriageInput, TriageVerdict


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_triage_input() -> TriageInput:
    return TriageInput(
        vacancy_id="v-001",
        title="Engineering Manager",
        company="Acme",
        location="Remote",
        job_text="Lead a QA team of 10 engineers.",
        claims=[
            ClaimRecord(claim_id="C-001", claim_text="Led QA team", status="verified"),
            ClaimRecord(claim_id="C-002", claim_text="15000 test-hours", status="verified"),
        ],
    )


_TRIAGE_RESPONSE = {
    "vacancy_id": "v-001",
    "verdict": "apply",
    "fit_summary": "Strong match: team lead experience.",
    "hard_requirements": [
        {"requirement": "Lead QA team", "status": "strong", "evidence_claim_ids": ["C-001"]}
    ],
    "material_unknowns": [],
    "overclaim_risks": [],
}

_RESUME_RESPONSE = {
    "bullets": [
        {"aid": "A-1", "phrased_text": "Delivered 15000 test-hours of automation."},
        {"aid": "A-2", "phrased_text": "Reduced defect escape rate by 40%."},
        # A-99 — выдуманный aid, должен быть отброшен
        {"aid": "A-99", "phrased_text": "Invented bullet with fabricated aid."},
    ]
}


def _mock_transport(response_body: dict):
    """Создаёт MockTransport, всегда возвращающий JSON ответа."""

    class _Transport(httpx.MockTransport):
        def __init__(self): pass  # noqa: D107

        def handle_request(self, request: httpx.Request) -> httpx.Response:
            # Проверяем заголовок Authorization
            assert request.headers.get("authorization", "").startswith("Bearer ")
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {"message": {"content": json.dumps(response_body)}}
                    ]
                },
            )

    return _Transport()


# ---------------------------------------------------------------------------
# Задача 1: triage_verdict
# ---------------------------------------------------------------------------

class TestTriageVerdict:
    def test_posts_to_chat_completions(self):
        """POST на .../chat/completions, авторизация Bearer, парсит TriageVerdict."""
        recorded: list[httpx.Request] = []

        class RecordingTransport(httpx.MockTransport):
            def __init__(self): pass

            def handle_request(self, request: httpx.Request) -> httpx.Response:
                recorded.append(request)
                return httpx.Response(
                    200,
                    json={"choices": [{"message": {"content": json.dumps(_TRIAGE_RESPONSE)}}]},
                )

        http = httpx.Client(transport=RecordingTransport())
        client = DeepSeekClient("sk-test", base_url="https://api.deepseek.com", http=http)

        verdict = client.triage_verdict(_make_triage_input())

        assert len(recorded) == 1
        req = recorded[0]
        assert req.url.path.endswith("/chat/completions")
        assert req.headers["authorization"] == "Bearer sk-test"

        body = json.loads(req.content)
        assert body["model"] == "deepseek-chat"
        msgs = body["messages"]
        assert msgs[0]["role"] == "system"
        assert msgs[1]["role"] == "user"

        assert isinstance(verdict, TriageVerdict)
        assert verdict.vacancy_id == "v-001"
        assert verdict.verdict == "apply"

    def test_system_prompt_mentions_only_and_claims(self):
        """Системный промпт содержит 'only' + ссылку на claims/evidence."""
        recorded: list[httpx.Request] = []

        class T(httpx.MockTransport):
            def __init__(self): pass

            def handle_request(self, request: httpx.Request) -> httpx.Response:
                recorded.append(request)
                return httpx.Response(
                    200,
                    json={"choices": [{"message": {"content": json.dumps(_TRIAGE_RESPONSE)}}]},
                )

        http = httpx.Client(transport=T())
        client = DeepSeekClient("sk-test", http=http)
        client.triage_verdict(_make_triage_input())

        body = json.loads(recorded[0].content)
        sys_prompt = body["messages"][0]["content"].lower()
        assert "only" in sys_prompt
        assert any(w in sys_prompt for w in ("claim", "evidence"))

    def test_user_contains_job_text_and_claim_ids(self):
        """User-сообщение содержит job_text и идентификаторы claims."""
        recorded: list[httpx.Request] = []

        class T(httpx.MockTransport):
            def __init__(self): pass

            def handle_request(self, request: httpx.Request) -> httpx.Response:
                recorded.append(request)
                return httpx.Response(
                    200,
                    json={"choices": [{"message": {"content": json.dumps(_TRIAGE_RESPONSE)}}]},
                )

        http = httpx.Client(transport=T())
        client = DeepSeekClient("sk-test", http=http)
        inp = _make_triage_input()
        client.triage_verdict(inp)

        body = json.loads(recorded[0].content)
        user_content = body["messages"][1]["content"]
        assert "15000 test-hours" in user_content or "Lead QA team" in user_content
        assert "C-001" in user_content

    def test_system_prompt_requires_categorical_skip_reason(self):
        """Системный промпт явно требует категорическую причину для skip (§3 CLAUDE.md) —
        soft-гэп на иначе подходящей роли не должен быть основанием для skip."""
        recorded: list[httpx.Request] = []

        class T(httpx.MockTransport):
            def __init__(self): pass

            def handle_request(self, request: httpx.Request) -> httpx.Response:
                recorded.append(request)
                return httpx.Response(
                    200,
                    json={"choices": [{"message": {"content": json.dumps(_TRIAGE_RESPONSE)}}]},
                )

        http = httpx.Client(transport=T())
        client = DeepSeekClient("sk-test", http=http)
        client.triage_verdict(_make_triage_input())

        body = json.loads(recorded[0].content)
        sys_prompt = body["messages"][0]["content"]
        for category in ("mandatory_language", "license_or_qualification",
                         "clearance_or_citizenship", "onsite_location", "domain_mismatch"):
            assert category in sys_prompt, f"missing category: {category}"
        assert "skip_category" in sys_prompt
        assert "NEVER grounds for" in sys_prompt

    def test_raises_on_empty_key(self):
        with pytest.raises(ValueError, match="api_key"):
            DeepSeekClient("")


# ---------------------------------------------------------------------------
# Задача 2: resume_phrasing + §3 фильтр aid
# ---------------------------------------------------------------------------

class TestResumePhrasing:
    def _make_req(self) -> PhrasingRequest:
        return PhrasingRequest(
            application_id="app-001",
            headline="Head of QA",
            bullets=[
                {"aid": "A-1", "source_text": "Delivered 15000 test-hours.", "source_metric": "15000"},
                {"aid": "A-2", "source_text": "Reduced defects.", "source_metric": "40%"},
            ],
        )

    def test_parses_and_preserves_aids(self):
        http = httpx.Client(transport=_mock_transport(_RESUME_RESPONSE))
        client = DeepSeekClient("sk-test", http=http)
        phrasing = client.resume_phrasing(self._make_req())

        # A-99 должен быть отброшен; A-1 и A-2 — сохранены
        aids = {b.aid for b in phrasing.bullets}
        assert "A-1" in aids
        assert "A-2" in aids

    def test_drops_aid_outside_input_set(self):
        """§3 фильтр: aid A-99, которого нет во входном множестве, отбрасывается."""
        http = httpx.Client(transport=_mock_transport(_RESUME_RESPONSE))
        client = DeepSeekClient("sk-test", http=http)
        phrasing = client.resume_phrasing(self._make_req())

        aids = {b.aid for b in phrasing.bullets}
        assert "A-99" not in aids, "Выдуманный aid A-99 должен быть отброшен фильтром"

    def test_application_id_preserved(self):
        http = httpx.Client(transport=_mock_transport(_RESUME_RESPONSE))
        client = DeepSeekClient("sk-test", http=http)
        phrasing = client.resume_phrasing(self._make_req())
        assert phrasing.application_id == "app-001"

    def test_empty_bullets_from_llm(self):
        """Если LLM вернул пустой список — ResumePhrasing с пустыми bullets."""
        empty = {"bullets": []}
        http = httpx.Client(transport=_mock_transport(empty))
        client = DeepSeekClient("sk-test", http=http)
        phrasing = client.resume_phrasing(self._make_req())
        assert phrasing.bullets == []


# ---------------------------------------------------------------------------
# LLM-parse-guard: кривой JSON → доменная LLMResponseError, не голый крах
# ---------------------------------------------------------------------------

def _malformed_transport(content: str = "{not valid json"):
    """MockTransport, возвращающий невалидный JSON в поле content ответа LLM."""

    class _Transport(httpx.MockTransport):
        def __init__(self): pass  # noqa: D107

        def handle_request(self, request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": content}}]},
            )

    return _Transport()


class TestLLMParseGuard:
    def test_resume_phrasing_raises_llm_response_error_on_malformed_json(self):
        http = httpx.Client(transport=_malformed_transport())
        client = DeepSeekClient("sk-test", http=http)
        req = PhrasingRequest(
            application_id="app-001",
            headline="Head of QA",
            bullets=[{"aid": "A-1", "source_text": "x", "source_metric": "1"}],
        )
        with pytest.raises(LLMResponseError):
            client.resume_phrasing(req)

    def test_triage_verdict_raises_llm_response_error_on_malformed_json(self):
        http = httpx.Client(transport=_malformed_transport())
        client = DeepSeekClient("sk-test", http=http)
        with pytest.raises(LLMResponseError):
            client.triage_verdict(_make_triage_input())


# ---------------------------------------------------------------------------
# Задача 3: client_from_env
# ---------------------------------------------------------------------------

class TestClientFromEnv:
    def test_raises_if_key_missing(self):
        with pytest.raises(ValueError, match="DEEPSEEK_API_KEY"):
            client_from_env({})

    def test_raises_if_key_empty(self):
        with pytest.raises(ValueError, match="DEEPSEEK_API_KEY"):
            client_from_env({"DEEPSEEK_API_KEY": ""})

    def test_creates_client_with_placeholder_key(self):
        c = client_from_env({"DEEPSEEK_API_KEY": "PLACEHOLDER"})
        assert isinstance(c, DeepSeekClient)

    def test_respects_base_url_and_model(self):
        c = client_from_env({
            "DEEPSEEK_API_KEY": "sk-x",
            "DEEPSEEK_BASE_URL": "https://custom.api",
            "DEEPSEEK_MODEL": "deepseek-coder",
        })
        assert c._base_url == "https://custom.api"
        assert c._model == "deepseek-coder"
