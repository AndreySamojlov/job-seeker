"""Read-only чтение вопросов формы Greenhouse (?questions=true). Парс отделён от сети."""
import httpx


def parse_questions(payload: dict) -> list[dict]:
    """payload GH job JSON -> [{label, required, fields:[name], options:[label]}]."""
    out = []
    for q in payload.get("questions", []):
        fields = [f.get("name") for f in q.get("fields", [])]
        options = []
        for f in q.get("fields", []):
            for v in (f.get("values") or []):
                if v.get("label") is not None:
                    options.append(v["label"])
        out.append({
            "label": q.get("label"),
            "required": bool(q.get("required")),
            "fields": fields,
            "options": options,
        })
    return out


def _questions_url(source_url: str) -> str:
    sep = "&" if "?" in source_url else "?"
    return f"{source_url}{sep}questions=true"


def fetch_questions(source_url: str, *, client=None) -> list[dict]:
    """GET source_url с questions=true, вернуть parse_questions. Read-only."""
    owns = client is None
    c = client or httpx.Client(timeout=15)
    try:
        resp = c.get(_questions_url(source_url))
        resp.raise_for_status()
        return parse_questions(resp.json())
    finally:
        if owns:
            c.close()
