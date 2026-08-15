from __future__ import annotations

from dataclasses import replace

from app.commands import CommandKind, ParsedCommand
from app.pioneer_client import extract_entities, guard_is_safe
from app.skus import resolve_sku

_LOCKED_KINDS = frozenset(
    {
        CommandKind.GOT_IT,
        CommandKind.RETURNING,
        CommandKind.CANCEL,
        CommandKind.SETTLE,
        CommandKind.YES,
        CommandKind.PAID,
    }
)


def _sku_from_entities(ents: dict[str, str]) -> str | None:
    for key in ("item", "connector"):
        span = ents.get(key)
        if span:
            sku = resolve_sku(span)
            if sku is not None:
                return sku
    return None


def enrich_command(text: str, parsed: ParsedCommand) -> ParsedCommand:
    if not guard_is_safe(text):
        return ParsedCommand(kind="UNSAFE", sku=None, loan_id=None, raw=text)

    ents = extract_entities(text)
    enriched = replace(parsed, entities=ents)

    if parsed.kind in _LOCKED_KINDS:
        return enriched

    if parsed.kind in (CommandKind.NEED, CommandKind.LEND):
        if parsed.sku is None:
            sku = _sku_from_entities(ents)
            if sku is not None:
                return replace(enriched, sku=sku)
        return enriched

    if parsed.kind != CommandKind.UNKNOWN:
        return enriched

    intent = ents.get("intent", "")
    item = ents.get("item", "")

    if intent in ("borrow", "need"):
        sku = resolve_sku(item or text)
        if sku is not None:
            return replace(enriched, kind=CommandKind.NEED, sku=sku)

    if intent == "lend":
        sku = resolve_sku(item or text)
        return replace(enriched, kind=CommandKind.LEND, sku=sku)

    return enriched
