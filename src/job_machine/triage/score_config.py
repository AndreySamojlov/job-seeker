"""Загрузка рубрики fit-2 из config/fit_score.json: веса семи векторов, мягкие пороги,
границы бэндов, шкалы hands-on/seniority, таблица смежности доменов, баллы гео.
Зеркалит паттерн gates_config.load_gate_config."""
import json
from dataclasses import dataclass
from pathlib import Path

_DEFAULT_PATH = Path(__file__).resolve().parents[3] / "config" / "fit_score.json"


@dataclass(frozen=True)
class ScoreConfig:
    version: str
    weights: dict[str, float]
    soft_floors: dict[str, int]
    band_thresholds: dict[str, int]
    status_points: dict[str, int]
    importance_weights: dict[str, float]
    hands_on_scale: dict[int, int]
    seniority_scale: dict[int, int]
    domain_points: dict[str, int]
    domain_adjacency: dict[str, list[str]]
    geo_points: dict[str, int]
    confidence_floor: float


def load_score_config(path: str | Path | None = None) -> ScoreConfig:
    p = Path(path) if path else _DEFAULT_PATH
    data = json.loads(p.read_text(encoding="utf-8"))
    return ScoreConfig(
        version=str(data["version"]),
        weights={k: float(v) for k, v in data["weights"].items()},
        soft_floors={k: int(v) for k, v in data["soft_floors"].items()},
        band_thresholds={k: int(v) for k, v in data["band_thresholds"].items()},
        status_points={k: int(v) for k, v in data["status_points"].items()},
        importance_weights={k: float(v) for k, v in data["importance_weights"].items()},
        # JSON не умеет целочисленные ключи — приводим здесь, один раз.
        hands_on_scale={int(k): int(v) for k, v in data["hands_on_scale"].items()},
        seniority_scale={int(k): int(v) for k, v in data["seniority_scale"].items()},
        domain_points={k: int(v) for k, v in data["domain_points"].items()},
        # Регистр нормализуем и в ключах: industry приходит из INDUSTRY_ENUM в нижнем
        # регистре, и ключ с заглавной буквой в JSON давал бы тихий промах поиска.
        domain_adjacency={k.lower(): [s.lower() for s in v]
                          for k, v in data["domain_adjacency"].items()},
        geo_points={k: int(v) for k, v in data["geo_points"].items()},
        confidence_floor=float(data["confidence_floor"]),
    )
