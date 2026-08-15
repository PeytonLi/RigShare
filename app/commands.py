from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

try:
    from app.skus import resolve_sku as _skus_resolve_sku
except ImportError:
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
    lower = text.lower()
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
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class ParsedCommand:
    kind: str
    sku: str | None
    loan_id: str | None
    raw: str


# People text "Got it!" and "returning!". Without this every such message parses
# as UNKNOWN and the loan silently stalls. Hyphens stay -- "usb-c" needs them.
_PUNCTUATION = str.maketrans("", "", "!.,?;:'\"")


def _normalize(text: str) -> str:
    return " ".join(text.translate(_PUNCTUATION).strip().split())


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
        return ParsedCommand(kind=CommandKind.LEND, sku=None, loan_id=None, raw=raw)

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

    if "need" in lower or "borrow" in lower:
        sku = _parse_need_sku(lower)
        if sku is not None:
            return ParsedCommand(kind=CommandKind.NEED, sku=sku, loan_id=None, raw=raw)

    return ParsedCommand(kind=CommandKind.UNKNOWN, sku=None, loan_id=None, raw=raw)
