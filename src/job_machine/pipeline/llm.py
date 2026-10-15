"""LLM-клиент pipeline: DeepSeek для triage-verdict и resume-phrasing.

Принципы §3:
- triage: только предоставленные claims, never invent; unknown → material_unknowns.
- resume: только source_text/source_metric из облака; preserve aid; §3 фильтр aid.
"""
from __future__ import annotations

import json
import os
from typing import Protocol, runtime_checkable

import httpx
from pydantic import ValidationError

from job_machine.http.retry import request_with_retry
from job_machine.mail.models import (
    ApplicationRef,
    EmailInput,
    MAIL_STRUCTURED_OUTPUT_SCHEMA,
    ReplyClassification,
)
from job_machine.resume.models import PhrasedBullet, PhrasingRequest, ResumePhrasing
from job_machine.triage.models import STRUCTURED_OUTPUT_SCHEMA, TriageInput, TriageVerdict


class LLMResponseError(Exception):
    """LLM вернул ответ, который не парсится в ожидаемую структуру.

    Доменная ошибка: pipeline-runner ловит её и помечает item заблокированным,
    а не падает голым JSONDecodeError/ValidationError.
    """

# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

_TRIAGE_SYS = (
    "You are a strict job-fit evaluator. "
    "Use ONLY the provided evidence claims to assess fit. "
    "Never invent new claims, numbers, or evidence. "
    "If a hard requirement cannot be evaluated from the given claims, "
    "mark it status='unknown' and add it to material_unknowns. "
    "verdict: \"apply\" (strong overall, no blocking gap), \"apply_with_caveat\" "
    "(good fit with honest caveats — INCLUDING soft skill/tool gaps on an otherwise "
    "matching role; this is the default for any gap that is not one of the 5 categorical "
    "exclusions below), \"skip\" — ONLY when the gap falls into one of these 5 "
    "categorical exclusions, and cannot be closed by relocation or sponsorship: "
    "(1) mandatory_language — the posting requires a specific language at a level the "
    "candidate's claims do not support; "
    "(2) license_or_qualification — a legally/formally required license or certification "
    "the candidate does not hold; "
    "(3) clearance_or_citizenship — security clearance or citizenship requirement; "
    "(4) onsite_location — mandatory on-site presence in a location the candidate cannot "
    "relocate to; "
    "(5) domain_mismatch — the role is in an entirely different functional domain, not an "
    "adjacent skill gap within a matching domain. "
    "A missing tool, technology, or years-of-experience within a role the candidate is "
    "otherwise qualified for is NEVER grounds for \"skip\" — use \"apply_with_caveat\" and "
    "list the gap in material_unknowns. "
    "skip_category: REQUIRED when verdict=\"skip\" — must be exactly one of the 5 values "
    "above (mandatory_language | license_or_qualification | clearance_or_citizenship | "
    "onsite_location | domain_mismatch). Omit/null otherwise. "
    "Output valid JSON matching the provided schema exactly."
)

_RESUME_SYS = (
    "You are a professional CV writer. "
    "For each bullet: rephrase source_text into polished English, "
    "using ONLY facts from source_text and source_metric. "
    "Never introduce new numbers, tools, employers, technologies, or claims "
    "not present in the source fields. "
    "Preserve the original aid for every bullet (one output per input bullet). "
    "Output JSON: {\"bullets\": [{\"aid\": \"...\", \"phrased_text\": \"...\"}]}."
)

_MAIL_SYS = (
    "You are an email classifier for job applications. "
    "Given one employer reply email and a list of the candidate's active "
    "applications, decide which application (if any) this email is about and "
    "what it means for the funnel. "
    "category='rejected' only for explicit rejections. "
    "category='interview_scheduled' only for explicit interview/screening "
    "invitations with a concrete next step. "
    "category='other' for anything ambiguous, an offer, a document/assessment "
    "request, or if no application matches confidently. "
    "If uncertain, prefer category='other' and lower confidence. "
    "Never invent an application_id not present in the provided list. "
    "Output valid JSON matching the provided schema exactly."
)


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------

@runtime_checkable
class LLMClient(Protocol):
    def triage_verdict(self, inp: TriageInput) -> TriageVerdict: ...
    def resume_phrasing(self, req: PhrasingRequest) -> ResumePhrasing: ...
    def classify_reply(
        self, email: EmailInput, applications: list[ApplicationRef]
    ) -> ReplyClassification: ...


# ---------------------------------------------------------------------------
# DeepSeek implementation
# ---------------------------------------------------------------------------

class DeepSeekClient:
    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://api.deepseek.com",
        model: str = "deepseek-chat",
        http: httpx.Client | None = None,
        timeout: float = 60.0,
        sleep=None,
    ) -> None:
        if not api_key:
            raise ValueError("api_key must not be empty")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._http = http or httpx.Client(timeout=timeout)
        self._sleep = sleep

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _chat(self, system: str, user: str) -> str:
        kwargs = {} if self._sleep is None else {"sleep": self._sleep}
        resp = request_with_retry(
            self._http, "POST", f"{self._base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self._api_key}"},
            json={
                "model": self._model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "response_format": {"type": "json_object"},
                "temperature": 0,
            },
            **kwargs,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def triage_verdict(self, inp: TriageInput) -> TriageVerdict:
        claim_lines = "\n".join(
            f"- {c.claim_id}: {c.claim_text} [{c.status}]"
            for c in inp.claims
        )
        user = (
            f"vacancy_id: {inp.vacancy_id}\n"
            f"title: {inp.title}\n"
            f"company: {inp.company}\n"
            f"location: {inp.location}\n"
            f"job_text:\n{inp.job_text}\n\n"
            f"Available evidence claims:\n{claim_lines}\n\n"
            f"Output schema:\n{json.dumps(STRUCTURED_OUTPUT_SCHEMA, indent=2)}"
        )
        raw = self._chat(_TRIAGE_SYS, user)
        try:
            return TriageVerdict.model_validate_json(raw)
        except (ValidationError, ValueError) as exc:
            raise LLMResponseError(
                f"triage_verdict: invalid LLM JSON (len={len(raw)})") from exc

    def resume_phrasing(self, req: PhrasingRequest) -> ResumePhrasing:
        # §3 детерминированный фильтр: множество допустимых aid из запроса
        allowed: set[str] = {b["aid"] for b in req.bullets}

        bullets_text = json.dumps(req.bullets, ensure_ascii=False, indent=2)
        user = (
            f"application_id: {req.application_id}\n"
            f"headline: {req.headline}\n\n"
            f"Bullets to rephrase:\n{bullets_text}"
        )
        raw = self._chat(_RESUME_SYS, user)
        try:
            data = json.loads(raw)
            # Строгий фильтр: выбрасываем любой aid не из входного множества
            bullets = [
                PhrasedBullet(aid=b["aid"], phrased_text=b["phrased_text"])
                for b in data.get("bullets", [])
                if b.get("aid") in allowed
            ]
        except (json.JSONDecodeError, KeyError, TypeError, AttributeError) as exc:
            raise LLMResponseError(
                f"resume_phrasing: invalid LLM JSON (len={len(raw)})") from exc
        return ResumePhrasing(application_id=req.application_id, bullets=bullets)

    def classify_reply(
        self, email: EmailInput, applications: list[ApplicationRef]
    ) -> ReplyClassification:
        apps_text = "\n".join(
            f"- application_id={a.application_id} candidate_id={a.candidate_id} "
            f"company={a.company} role={a.role}"
            for a in applications
        ) or "(no active applications)"
        user = (
            f"From: {email.from_addr}\n"
            f"Subject: {email.subject}\n"
            f"Body:\n{email.body}\n\n"
            f"Candidate's active applications:\n{apps_text}\n\n"
            f"Output schema:\n{json.dumps(MAIL_STRUCTURED_OUTPUT_SCHEMA, indent=2)}"
        )
        raw = self._chat(_MAIL_SYS, user)
        try:
            return ReplyClassification.model_validate_json(raw)
        except (ValidationError, ValueError) as exc:
            raise LLMResponseError(
                f"classify_reply: invalid LLM JSON (len={len(raw)})") from exc


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def client_from_env(env: dict | None = None) -> DeepSeekClient:
    """Создать DeepSeekClient из переменных окружения.

    Читает: DEEPSEEK_API_KEY (обязательно), DEEPSEEK_BASE_URL, DEEPSEEK_MODEL.
    Поднимает ValueError если ключ не задан или пуст.
    """
    source = env if env is not None else os.environ
    api_key = source.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        raise ValueError("DEEPSEEK_API_KEY is not set or empty")
    kwargs: dict = {}
    base_url = source.get("DEEPSEEK_BASE_URL")
    if base_url:
        kwargs["base_url"] = base_url
    model = source.get("DEEPSEEK_MODEL")
    if model:
        kwargs["model"] = model
    return DeepSeekClient(api_key, **kwargs)
