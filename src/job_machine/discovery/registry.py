import json


def load_board_tokens(path: str = "config/greenhouse_boards.json") -> list[str]:
    """Загрузить board-токены Greenhouse из config-файла (dedup + strip, порядок сохранён)."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    seen: set[str] = set()
    out: list[str] = []
    for raw in data.get("boards", []):
        token = raw.strip()
        if token and token not in seen:
            seen.add(token)
            out.append(token)
    return out
