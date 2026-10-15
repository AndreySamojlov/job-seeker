"""Воспроизводимые хеши пакета (контур безопасности §3). Без таймстемпов в payload —
один и тот же логический пакет всегда даёт один и тот же payload_hash, к которому
привяжется approval-токен (guard NoSubmitIfPayloadHashChanged)."""
import hashlib
import json


def _canon(obj) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _answer_pairs(answers) -> list[dict]:
    return sorted(({"field": a.field, "value": a.value} for a in answers),
                  key=lambda d: d["field"])


def _consent_pairs(consents) -> list[dict]:
    return sorted(({"field": c.field, "decision": c.decision} for c in consents),
                  key=lambda d: d["field"])


def answers_hash(answers) -> str:
    return _sha(_canon(_answer_pairs(answers)))


def consents_hash(consents) -> str:
    return _sha(_canon(_consent_pairs(consents)))


def payload_hash(destination_url: str, resume_content_hash: str,
                 answers, consents) -> str:
    payload = {
        "destination_url": destination_url,
        "resume_content_hash": resume_content_hash,
        "answers": _answer_pairs(answers),
        "consents": _consent_pairs(consents),
    }
    return _sha(_canon(payload))
