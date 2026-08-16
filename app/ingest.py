from __future__ import annotations

from dataclasses import replace

from app.commands import CommandKind, ParsedCommand, parse_amount_cents
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


def _prices_from_entities(cmd: ParsedCommand, ents: dict[str, str]) -> ParsedCommand:
    """Let the fine-tuned NER set the price when the regex found no bare number.

    "LEND HDMI $15 for $3" is parsed deterministically; "lending my hdmi, 15 hold
    and 3 for me" is not, and that is the sentence GLiNER2 is trained for. The
    regex still wins when it fired -- a typed number is not a guess.
    """
    if cmd.deposit_cents is not None:
        return cmd
    deposit = parse_amount_cents(ents.get("deposit"))
    if deposit is None:
        return cmd
    rental = parse_amount_cents(ents.get("rental_fee"))
    return replace(cmd, deposit_cents=deposit, rental_cents=rental)


def _sku_from_entities(ents: dict[str, str]) -> str | None:
    for key in ("item", "connector"):
        span = ents.get(key)
        if span:
            sku = resolve_sku(span)
            if sku is not None:
                return sku
    return None


def enrich_command(text: str, parsed: ParsedCommand) -> ParsedCommand:
    # The guard only gets a vote on free text. An exact command already parsed
    # deterministically and never reaches a model prompt, so a false positive there
    # costs us a loan for nothing -- GLiGuard calls "LEND HDMI $15 for $3" unsafe.
    # PRD 5: commands are the fallback that cannot die on a parse miss.
    if parsed.kind == CommandKind.UNKNOWN and not guard_is_safe(text):
        return ParsedCommand(kind="UNSAFE", sku=None, loan_id=None, raw=text)

    ents = extract_entities(text)
    enriched = replace(parsed, entities=ents)

    if parsed.kind in _LOCKED_KINDS:
        return enriched

    if parsed.kind in (CommandKind.NEED, CommandKind.LEND):
        if parsed.sku is None:
            sku = _sku_from_entities(ents)
            if sku is not None:
                enriched = replace(enriched, sku=sku)
        if parsed.kind == CommandKind.LEND:
            enriched = _prices_from_entities(enriched, ents)
        return enriched

    if parsed.kind != CommandKind.UNKNOWN:
        return enriched

    intent = ents.get("intent", "")
    item = ents.get("item", "")

    if intent.startswith(("borrow", "need")):
        sku = resolve_sku(item or text)
        if sku is not None:
            return replace(enriched, kind=CommandKind.NEED, sku=sku)

    if intent.startswith("lend"):
        sku = resolve_sku(item or text)
        return _prices_from_entities(
            replace(enriched, kind=CommandKind.LEND, sku=sku), ents
        )

    return enriched
