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


# PRD 4.5: we hold the deposit, so we are not allowed to hold interesting money.
# A cable people forget is the product; a laptop is someone else's insurance.
MAX_DEPOSIT_CENTS = 8000
MIN_DEPOSIT_CENTS = 50  # Linq's floor. Below this the payment request 4xxs.

_PROHIBITED = (
    "laptop", "macbook", "notebook computer",
    "phone", "iphone", "android", "pixel",
    "camera", "gopro", "dslr",
    "tablet", "ipad",
    "headphone", "airpod", "earbud", "headset",
    "watch", "airtag",
    "kindle", "switch", "steam deck", "drone",
)


def get_sku(sku: str) -> Sku:
    return SKUS[sku]


# "laptop charger" and "macbook cable" are exactly the inventory we want -- the
# banned word describes what the accessory plugs into, not what is being lent.
_ACCESSORY = ("charger", "cable", "cord", "brick", "adapter", "dongle", "hub", "plug")


def prohibited_item(text: str) -> str | None:
    """The banned word if the lender is trying to list something we won't hold."""
    normalized = text.strip().lower()
    for word in _PROHIBITED:
        index = normalized.find(word)
        if index == -1:
            continue
        if any(accessory in normalized[index + len(word):] for accessory in _ACCESSORY):
            continue
        return word
    return None


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
