"""Загрузка конфига Telegram-каналов (config/telegram_channels.json)."""
import json
from dataclasses import dataclass


@dataclass(frozen=True)
class ChannelSpec:
    handle: str
    category: str
    note: str | None = None


def load_channels(path: str = "config/telegram_channels.json") -> list[ChannelSpec]:
    """Загрузить и дедуплицировать каналы (dedup по handle, ведущий @ срезается)."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    seen: set[str] = set()
    out: list[ChannelSpec] = []
    for entry in data.get("channels", []):
        handle = (entry.get("handle") or "").strip().lstrip("@")
        category = (entry.get("category") or "").strip()
        if not handle or not category:
            continue
        if handle in seen:
            continue
        seen.add(handle)
        out.append(ChannelSpec(handle=handle, category=category, note=entry.get("note")))
    return out
