"""Загрузка глобальных таксономий детерминированных триаж-гейтов из config/triage_gates.json."""
import json
from dataclasses import dataclass
from pathlib import Path

_DEFAULT_PATH = Path(__file__).resolve().parents[3] / "config" / "triage_gates.json"


@dataclass(frozen=True)
class GateConfig:
    role_family_map: dict[str, list[str]]
    level_bands: list[str]
    level_keywords: dict[str, list[str]]
    level_up_tolerance: int
    level_down_tolerance: int
    geo_region_map: dict[str, list[str]]
    geo_global_tokens: list[str]
    company_daily_cap_default: int


def load_gate_config(path: str | Path | None = None) -> GateConfig:
    p = Path(path) if path else _DEFAULT_PATH
    data = json.loads(p.read_text(encoding="utf-8"))
    return GateConfig(
        role_family_map={k: [s.lower() for s in v] for k, v in data["role_family_map"].items()},
        level_bands=list(data["level_bands"]),
        level_keywords={k: [s.lower() for s in v] for k, v in data["level_keywords"].items()},
        level_up_tolerance=int(data["level_up_tolerance"]),
        level_down_tolerance=int(data["level_down_tolerance"]),
        geo_region_map={k: [s.lower() for s in v] for k, v in data["geo_region_map"].items()},
        geo_global_tokens=[s.lower() for s in data["geo_global_tokens"]],
        company_daily_cap_default=int(data["company_daily_cap_default"]),
    )
