# coding: utf-8
"""Слияние глобальных и per-application ответов. Pure, без I/O.

Per-app выигрывает по нормализованному `field` (lower + только буквы/цифры/пробел,
схлоп пробелов) — та же нормализация, что в fill/adapter, чтобы матч был согласован.
"""
import re

from job_machine.package.models import AnswerRecord


def _norm(text: str) -> str:
    s = re.sub(r"[^a-z0-9 ]+", " ", (text or "").lower())
    return re.sub(r"\s+", " ", s).strip()


def merge_answers(global_answers, app_answers) -> list[AnswerRecord]:
    by_key: dict[str, AnswerRecord] = {}
    for a in global_answers:
        by_key[_norm(a.field)] = a
    for a in app_answers:  # per-app перекрывает глобальный по тому же нормализованному полю
        by_key[_norm(a.field)] = a
    return list(by_key.values())
