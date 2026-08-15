#!/usr/bin/env python3
"""Saturday catalog survey: which cables people actually borrow.

    python scripts/terac_catalog_survey.py

Creates a general-population survey on the RigShare Terac project, tallies
votes into data/catalog_weights.json (weight = 1 + vote count), and prints
the weights path.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from app.catalog import WEIGHTS_PATH, load_weights, write_weights
from app.config import get_settings
from app.terac_client import launch_catalog_survey, list_submissions

LABEL_TO_SKU = {
    "HDMI": "hdmi",
    "USB-C charger": "usbc_charger",
    "Lightning": "lightning_cable",
    "dongle": "usbc_hub",
}
_LABEL_LOOKUP = {label.lower(): sku for label, sku in LABEL_TO_SKU.items()}
_SKUS = ("hdmi", "usbc_charger", "lightning_cable", "usbc_hub")
_ANSWER_KEYS = (
    "screening_answers",
    "answers",
    "answer",
    "responses",
    "result",
    "results",
    "choices",
)


def _walk_texts(value: object) -> list[str]:
    texts: list[str] = []
    if isinstance(value, str):
        texts.append(value)
    elif isinstance(value, list):
        for item in value:
            texts.extend(_walk_texts(item))
    elif isinstance(value, dict):
        for key in ("answer", "answers", "text", "value", "label", "option", "choice"):
            if key in value:
                texts.extend(_walk_texts(value[key]))
    return texts


def _answers_from_submission(row: dict) -> list[str]:
    texts: list[str] = []
    for key in _ANSWER_KEYS:
        if key in row:
            texts.extend(_walk_texts(row[key]))
    inner = row.get("data")
    if isinstance(inner, dict):
        texts.extend(_answers_from_submission(inner))
    return texts


def _sku_votes(submissions: list[dict]) -> Counter[str]:
    votes: Counter[str] = Counter()
    for row in submissions:
        if not isinstance(row, dict):
            continue
        for blob in _answers_from_submission(row):
            for part in [piece.strip() for piece in blob.replace(",", "/").split("/")]:
                sku = _LABEL_LOOKUP.get(part.lower())
                if sku:
                    votes[sku] += 1
    return votes


def refresh_weights(opportunity_id: str | None) -> Path:
    weights = load_weights()
    submissions: list[dict] = []
    if opportunity_id:
        try:
            submissions = list_submissions(opportunity_id) or []
        except Exception:
            submissions = []
    votes = _sku_votes(submissions) if submissions else Counter()
    if votes:
        for sku in _SKUS:
            weights[sku] = 1.0 + votes.get(sku, 0)
    write_weights(weights)
    print(WEIGHTS_PATH)
    return WEIGHTS_PATH


def main() -> int:
    get_settings.cache_clear()
    settings = get_settings()
    if not settings.terac_api_key or not settings.terac_project_id:
        print("TERAC_API_KEY / TERAC_PROJECT_ID missing")
        return 1
    opportunity_id = launch_catalog_survey(
        "Which of these have you actually needed to borrow at a hackathon or conference?",
        ["HDMI", "USB-C charger", "Lightning", "dongle", "clicker", "none"],
    )
    if opportunity_id:
        print(f"launched {opportunity_id}")
        print("https://terac.com")
    else:
        print("create failed (see logs)")
    refresh_weights(opportunity_id)
    return 0 if opportunity_id else 1


if __name__ == "__main__":
    raise SystemExit(main())
