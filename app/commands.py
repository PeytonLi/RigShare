from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

try:
    from app.skus import fold_usbc as _fold_usbc
    from app.skus import resolve_sku as _skus_resolve_sku
except ImportError:
    _fold_usbc = None
    _skus_resolve_sku = None

_SKU_ALIASES: dict[str, str] = {
    "usb-c": "usbc_charger",
    "usbc": "usbc_charger",
    "charger": "usbc_charger",
    "lightning": "lightning_cable",
    "hdmi": "hdmi",
    "dongle": "usbc_hub",
    "hub": "usbc_hub",
}


def _local_resolve_sku(text: str) -> str | None:
    lower = _fold_usbc(text) if _fold_usbc is not None else text.lower()
    for alias, sku in _SKU_ALIASES.items():
        if alias in lower:
            return sku
    return None


def _parse_need_sku(text: str) -> str | None:
    if _skus_resolve_sku is not None:
        try:
            return _skus_resolve_sku(text)
        except NotImplementedError:
            pass
    return _local_resolve_sku(text)


class CommandKind(StrEnum):
    LEND = "LEND"
    NEED = "NEED"
    YES = "YES"
    GOT_IT = "GOT_IT"
    RETURNING = "RETURNING"
    CANCEL = "CANCEL"
    SETTLE = "SETTLE"
    PAID = "PAID"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class ParsedCommand:
    kind: str
    sku: str | None
    loan_id: str | None
    raw: str
    # Lender-set price, in cents. None means "use the SKU table".
    deposit_cents: int | None = None
    rental_cents: int | None = None
    entities: dict[str, str] | None = None


# "LEND HDMI 20", "LEND HDMI $20", "LEND HDMI $20 for $3", "LEND HDMI 20/3".
# The trailing boundary is what keeps "hdmi 6ft" and "usb-c 100w" out of the money:
# a digit glued to letters is a spec, a standalone number is a price.
_AMOUNT = re.compile(r"\$?\b(\d+(?:\.\d{1,2})?)\b(?![\w.])")


def parse_amount_cents(text: str | None) -> int | None:
    """First dollar amount in a span, in cents. For NER spans like "$15" or "15 bucks"."""
    if not text:
        return None
    found = _AMOUNT.findall(text)
    return int(round(float(found[0]) * 100)) if found else None


def _parse_prices(text: str) -> tuple[int | None, int | None]:
    """First number is the deposit, second is the rental. Both in dollars."""
    amounts = [int(round(float(found) * 100)) for found in _AMOUNT.findall(text)]
    if not amounts:
        return None, None
    if len(amounts) == 1:
        return amounts[0], None
    return amounts[0], amounts[1]


# People text "Got it!" and "returning!"; without stripping, those parse as
# UNKNOWN and the loan silently stalls. A '.' or ',' *between digits* is kept --
# blanket stripping turned "$20.50" into 2050 dollars, a 100x overcharge.
# Hyphens always stay: "usb-c" needs them.
_PUNCTUATION = re.compile(r"(?<!\d)[.,]|[.,](?!\d)|[!?;:'\"]")


def _normalize(text: str) -> str:
    return " ".join(_PUNCTUATION.sub("", text).strip().split())


def parse_command(text: str) -> ParsedCommand:
    raw = text
    normalized = _normalize(text)
    if not normalized:
        return ParsedCommand(
            kind=CommandKind.UNKNOWN, sku=None, loan_id=None, raw=raw
        )

    lower = normalized.lower()
    tokens = lower.split()
    first = tokens[0]

    if first == "lend":
        deposit, rental = _parse_prices(" ".join(tokens[1:]))
        return ParsedCommand(
            kind=CommandKind.LEND,
            sku=None,
            loan_id=None,
            raw=raw,
            deposit_cents=deposit,
            rental_cents=rental,
        )

    if first == "need":
        remainder = " ".join(tokens[1:])
        sku = _parse_need_sku(remainder or lower)
        return ParsedCommand(kind=CommandKind.NEED, sku=sku, loan_id=None, raw=raw)

    if first == "yes":
        return ParsedCommand(kind=CommandKind.YES, sku=None, loan_id=None, raw=raw)

    if first == "got":
        if len(tokens) >= 2 and tokens[1] == "it":
            return ParsedCommand(
                kind=CommandKind.GOT_IT, sku=None, loan_id=None, raw=raw
            )
    elif first == "gotit":
        return ParsedCommand(kind=CommandKind.GOT_IT, sku=None, loan_id=None, raw=raw)

    if first == "returning":
        return ParsedCommand(
            kind=CommandKind.RETURNING, sku=None, loan_id=None, raw=raw
        )

    if first == "cancel":
        return ParsedCommand(kind=CommandKind.CANCEL, sku=None, loan_id=None, raw=raw)

    if first == "settle":
        loan_id = tokens[1] if len(tokens) > 1 else None
        return ParsedCommand(
            kind=CommandKind.SETTLE, sku=None, loan_id=loan_id, raw=raw
        )

    if first == "paid" or lower in {"i paid", "i've paid", "already paid"}:
        return ParsedCommand(kind=CommandKind.PAID, sku=None, loan_id=None, raw=raw)

    if "need" in lower or "borrow" in lower:
        sku = _parse_need_sku(lower)
        if sku is not None:
            return ParsedCommand(kind=CommandKind.NEED, sku=sku, loan_id=None, raw=raw)

    # "usbc" / "USB-C" / "usb c" with no NEED prefix is still a borrow.
    folded = _fold_usbc(lower) if _fold_usbc is not None else lower
    if folded == "usbc":
        sku = _parse_need_sku(lower)
        if sku is not None:
            return ParsedCommand(kind=CommandKind.NEED, sku=sku, loan_id=None, raw=raw)

    return ParsedCommand(kind=CommandKind.UNKNOWN, sku=None, loan_id=None, raw=raw)
