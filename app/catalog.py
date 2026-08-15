"""Saturday Terac survey output. Matcher prompt and auto-pick read this file."""

from __future__ import annotations

import json
from pathlib import Path

from app.models import Item

WEIGHTS_PATH = Path(__file__).resolve().parent.parent / "data" / "catalog_weights.json"

_DEFAULTS = {
    "usbc_charger": 3.0,
    "hdmi": 2.0,
    "lightning_cable": 2.0,
    "usbc_hub": 1.0,
}


def load_weights() -> dict[str, float]:
    weights = dict(_DEFAULTS)
    try:
        raw = json.loads(WEIGHTS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return weights
    if isinstance(raw, dict):
        for sku, value in raw.items():
            try:
                weights[str(sku)] = float(value)
            except (TypeError, ValueError):
                continue
    return weights


def sku_weight(sku: str) -> float:
    return load_weights().get(sku, 0.0)


def sort_items(items: list[Item]) -> list[Item]:
    return sorted(items, key=lambda item: (-sku_weight(item.sku), item.created_at or item.id))


def write_weights(weights: dict[str, float]) -> None:
    WEIGHTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    WEIGHTS_PATH.write_text(json.dumps(weights, indent=2) + "\n", encoding="utf-8")
