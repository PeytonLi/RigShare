"""Growth + Product desks: Terac votes become copy, SKU order, and Matcher bias.

Defaults are the before. `apply_votes` writes `product_state.json` — that file is
the after. Do not auto-apply from the survey POST; screenshot the tallies first.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

_STATE_PATH = Path(__file__).with_name("product_state.json")

CATALOG_OPTIONS: tuple[tuple[str, str], ...] = (
    ("usbc_charger", "USB-C charger"),
    ("lightning_cable", "Lightning"),
    ("hdmi", "HDMI"),
    ("usbc_hub", "dongle"),
    ("clicker", "clicker"),
)
CATALOG_LABELS: dict[str, str] = {sku: label for sku, label in CATALOG_OPTIONS}
LABEL_TO_SKU: dict[str, str] = {label: sku for sku, label in CATALOG_OPTIONS}
NONE_LABEL = "none"

PITCH_A = "Need a charger? $25 hold, $18 back when you return it."
PITCH_B = "Borrow a taped USB-C over iMessage. Apple Pay in this thread."
PITCHES = {"a": PITCH_A, "b": PITCH_B}

DEFAULT_SKU_PRIORITY = [sku for sku, _ in CATALOG_OPTIONS]


@dataclass(frozen=True)
class ProductState:
    sku_priority: list[str]
    pitch_variant: str
    fee_tone: str
    applied: bool
    growth_detail: str
    product_detail: str


def _dollars(cents: int) -> str:
    if cents % 100 == 0:
        return f"${cents // 100}"
    return f"${cents / 100:.2f}"


def default_state() -> ProductState:
    return ProductState(
        sku_priority=list(DEFAULT_SKU_PRIORITY),
        pitch_variant="a",
        fee_tone="fair",
        applied=False,
        growth_detail="no Terac votes applied yet",
        product_detail="HDMI = USB-C = Lightning (table order)",
    )


def load_state() -> ProductState:
    path = _STATE_PATH
    if not path.exists():
        return default_state()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default_state()
    priority = [s for s in raw.get("sku_priority") or [] if isinstance(s, str)]
    pitch = raw.get("pitch_variant") if raw.get("pitch_variant") in PITCHES else "a"
    tone = raw.get("fee_tone") if raw.get("fee_tone") in {"fair", "greedy", "confusing"} else "fair"
    return ProductState(
        sku_priority=priority or list(DEFAULT_SKU_PRIORITY),
        pitch_variant=pitch,
        fee_tone=tone,
        applied=bool(raw.get("applied")),
        growth_detail=str(raw.get("growth_detail") or ""),
        product_detail=str(raw.get("product_detail") or ""),
    )


def save_state(state: ProductState) -> None:
    _STATE_PATH.write_text(json.dumps(asdict(state), indent=2) + "\n", encoding="utf-8")


def live_reply() -> str:
    state = load_state()
    return (
        f"RigShare is live. {PITCHES[state.pitch_variant]} "
        "LEND or NEED HDMI / USB-C / LIGHTNING."
    )


def fee_sentence(fee_cents: int) -> str:
    amount = _dollars(fee_cents)
    tone = load_state().fee_tone
    if tone == "greedy":
        return f"{amount} covers Apple Pay and the hold."
    if tone == "confusing":
        return f"{amount} to RigShare (not taken from the lender)."
    return f"{amount} RigShare fee."


def borrower_quote(
    title: str,
    deposit_cents: int,
    rental_cents: int,
    fee_cents: int,
    refund: int,
) -> str:
    state = load_state()
    hold = _dollars(deposit_cents)
    rental = _dollars(rental_cents)
    back = _dollars(refund)
    fee_bit = fee_sentence(fee_cents)
    if state.pitch_variant == "b":
        return (
            f"{title} nearby, marked with orange tape. Apple Pay in this thread. "
            f"{hold} hold now. {rental} to the lender if you bring it back. "
            f"{fee_bit} {back} refunded."
        )
    return (
        f"{title} nearby, marked with orange tape. "
        f"{hold} hold now. {back} back when you return it. "
        f"{rental} to the lender. {fee_bit}"
    )


def matcher_brief() -> str:
    labels = [CATALOG_LABELS.get(sku, sku) for sku in load_state().sku_priority]
    return "Prefer listed items in this order: " + ", ".join(labels) + "."


def sku_sort_key(sku: str) -> int:
    try:
        return load_state().sku_priority.index(sku)
    except ValueError:
        return 99


def tally(session: Session) -> dict:
    from app.models import SurveyResponse

    rows = session.execute(select(SurveyResponse)).scalars().all()
    catalog: Counter[str] = Counter()
    pitches: Counter[str] = Counter()
    fees: Counter[str] = Counter()
    for row in rows:
        try:
            labels = json.loads(row.catalog_json)
        except json.JSONDecodeError:
            labels = []
        if not isinstance(labels, list):
            labels = []
        for label in labels:
            if label == NONE_LABEL:
                continue
            catalog[str(label)] += 1
        if row.pitch in PITCHES:
            pitches[row.pitch] += 1
        if row.fee_tone in {"fair", "greedy", "confusing"}:
            fees[row.fee_tone] += 1
    return {
        "n": len(rows),
        "catalog": dict(catalog),
        "pitches": dict(pitches),
        "fees": dict(fees),
    }


def apply_votes(session: Session) -> ProductState:
    """Turn stored Terac responses into the live catalog / pitch / fee copy."""
    counts = tally(session)
    ranked_labels = [label for label, _ in Counter(counts["catalog"]).most_common()]
    priority: list[str] = []
    for label in ranked_labels:
        sku = LABEL_TO_SKU.get(label)
        if sku and sku not in priority:
            priority.append(sku)
    for sku in DEFAULT_SKU_PRIORITY:
        if sku not in priority:
            priority.append(sku)

    pitch_counts = counts["pitches"]
    pitch = max(PITCHES, key=lambda key: pitch_counts.get(key, 0)) if pitch_counts else "a"
    if pitch_counts.get("a", 0) == pitch_counts.get("b", 0) and pitch_counts:
        pitch = "a"

    fee_counts = counts["fees"]
    tone = "fair"
    if fee_counts:
        tone = max(("fair", "greedy", "confusing"), key=lambda key: fee_counts.get(key, 0))

    labels = [CATALOG_LABELS.get(sku, sku) for sku in priority]
    n = counts["n"]
    a_votes = pitch_counts.get("a", 0)
    b_votes = pitch_counts.get("b", 0)
    winner_votes = b_votes if pitch == "b" else a_votes
    state = ProductState(
        sku_priority=priority,
        pitch_variant=pitch,
        fee_tone=tone,
        applied=True,
        growth_detail=f"pitch {pitch.upper()} shipped ({winner_votes}/{n} votes)" if n else "no votes",
        product_detail=" → ".join(labels) + f" ({n} responses)",
    )
    save_state(state)
    from app.catalog import load_weights, write_weights

    weights = load_weights()
    rank = len(priority)
    for sku in priority:
        weights[sku] = float(rank)
        rank -= 1
    write_weights(weights)
    return state
