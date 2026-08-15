from __future__ import annotations

from app.commands import CommandKind, ParsedCommand
from app.pioneer_client import extract_entities, guard_is_safe
from app.skus import resolve_sku


def enrich_command(text: str, parsed: ParsedCommand) -> ParsedCommand:
    if not guard_is_safe(text):
        return ParsedCommand(kind="UNSAFE", sku=None, loan_id=None, raw=text)

    if parsed.kind != CommandKind.UNKNOWN:
        return parsed

    ents = extract_entities(text)
    intent = ents.get("intent", "")
    item = ents.get("item", "")

    if intent in ("borrow", "need"):
        sku = resolve_sku(item or text)
        if sku is not None:
            return ParsedCommand(
                kind=CommandKind.NEED, sku=sku, loan_id=None, raw=text
            )

    if intent == "lend":
        sku = resolve_sku(item or text)
        return ParsedCommand(
            kind=CommandKind.LEND, sku=sku, loan_id=None, raw=text
        )

    return parsed
