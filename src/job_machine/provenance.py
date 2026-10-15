"""Детерминированный content-hash снимка vault (контур провенанса §3, B7).

claims_version / answers_version штампуются рядом с triage/package-артефактом,
чтобы дрейф vault между прогонами был аудируем. НЕ входят в payload_hash.
Чистая функция: без I/O, сети, LLM. _canon/_sha намеренно локальны — модуль не
зависит ни от triage, ни от package (callers передают plain record-объекты).
"""
import hashlib
import json


def _canon(rows: list[dict]) -> str:
    return json.dumps(rows, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def claims_version(claims) -> str:
    rows = sorted(
        ({"claim_id": c.claim_id, "claim_text": c.claim_text, "status": c.status,
          "proof": c.proof, "safe_use": c.safe_use} for c in claims),
        key=lambda d: d["claim_id"])
    return _sha(_canon(rows))


def answers_version(answers) -> str:
    rows = sorted(
        ({"field": a.field, "value": a.value, "state": a.state, "rule": a.rule}
         for a in answers),
        key=lambda d: d["field"])
    return _sha(_canon(rows))
