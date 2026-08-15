from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Sku:
    id: str
    deposit_cents: int
    rental_cents: int
    platform_fee_cents: int = 200


_SKU_ROWS: tuple[tuple[str, int, int], ...] = (
    ("usbc_charger", 2500, 500),
    ("lightning_cable", 1500, 300),
    ("usbc_cable", 1200, 200),
    ("hdmi", 1500, 300),
    ("usbc_hdmi", 2000, 500),
    ("usbc_hub", 3000, 800),
    ("lightning_usbc", 1500, 300),
    ("clicker", 2500, 500),
)

SKUS: dict[str, Sku] = {
    sku_id: Sku(id=sku_id, deposit_cents=deposit, rental_cents=rental)
    for sku_id, deposit, rental in _SKU_ROWS
}


def get_sku(sku: str) -> Sku:
    return SKUS[sku]


def resolve_sku(text: str) -> str | None:
    normalized = text.strip().lower()

    if "lightning to usb" in normalized or "lightning-usbc" in normalized:
        return "lightning_usbc"
    if "usb-c to hdmi" in normalized or "usbc hdmi" in normalized:
        return "usbc_hdmi"
    if any(token in normalized for token in ("dongle", "hub", "multiport")):
        return "usbc_hub"
    if "hdmi" in normalized:
        return "hdmi"
    if "lightning" in normalized:
        return "lightning_cable"
    if any(
        token in normalized
        for token in ("usb-c", "usbc", "charger", "gan", "anker")
    ):
        return "usbc_charger"

    return None
