"""Детерминированный per-candidate headline по роль-семейству
(config/resume_headlines.json). Без LLM.

Конфиг — словарь candidate_id -> список записей {keywords, headline}. Кандидат без
записей (нет ключа / пустой список) получает fallback без попытки матчинга — канные
фразы применяются только к тому кандидату, для которого явно одобрены; никогда не
подставляются другому кандидату по совпадению ключевых слов роли (§3: не приписывать
чужой уровень руководства).

Роль вакансии casefold → взвешенный best-match по бакетам keyword-фраз: скор =
(число совпавших фраз, длина самой длинной совпавшей фразы, порядок в конфиге).
Нет совпадений / пустая роль / нет записей у кандидата → fallback (обычно —
перестановка половинок реального title, см. selector._choose_headline).
"""
import json
from pathlib import Path

_PATH = Path(__file__).resolve().parents[3] / "config" / "resume_headlines.json"


def _load(candidate_id: str) -> list[dict]:
    data = json.loads(_PATH.read_text(encoding="utf-8"))
    return data.get(candidate_id, [])


def headline_for_role(candidate_id: str, role: str | None, fallback: str) -> str:
    entries = _load(candidate_id)
    if not entries:
        return fallback
    low = (role or "").lower()
    if not low.strip():
        return fallback
    best_headline = None
    best_score = (0, 0, 0)
    for idx, entry in enumerate(entries):
        matched = [k for k in entry["keywords"] if k in low]
        if not matched:
            continue
        score = (len(matched), max(len(k) for k in matched), -idx)
        if score > best_score:
            best_score = score
            best_headline = entry["headline"]
    return best_headline if best_headline is not None else fallback
