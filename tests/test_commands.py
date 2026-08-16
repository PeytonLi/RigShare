from __future__ import annotations

import pytest

from app.commands import CommandKind, ParsedCommand, parse_command


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("LEND", ParsedCommand(kind=CommandKind.LEND, sku=None, loan_id=None, raw="LEND")),
        ("  lend  ", ParsedCommand(kind=CommandKind.LEND, sku=None, loan_id=None, raw="  lend  ")),
        ("YES", ParsedCommand(kind=CommandKind.YES, sku=None, loan_id=None, raw="YES")),
        ("RETURNING", ParsedCommand(kind=CommandKind.RETURNING, sku=None, loan_id=None, raw="RETURNING")),
        ("CANCEL", ParsedCommand(kind=CommandKind.CANCEL, sku=None, loan_id=None, raw="CANCEL")),
        (
            "GOT IT",
            ParsedCommand(kind=CommandKind.GOT_IT, sku=None, loan_id=None, raw="GOT IT"),
        ),
        (
            "got it",
            ParsedCommand(kind=CommandKind.GOT_IT, sku=None, loan_id=None, raw="got it"),
        ),
        (
            "GOTIT",
            ParsedCommand(kind=CommandKind.GOT_IT, sku=None, loan_id=None, raw="GOTIT"),
        ),
        (
            "SETTLE loan_abc123",
            ParsedCommand(
                kind=CommandKind.SETTLE,
                sku=None,
                loan_id="loan_abc123",
                raw="SETTLE loan_abc123",
            ),
        ),
        ("PAID", ParsedCommand(kind=CommandKind.PAID, sku=None, loan_id=None, raw="PAID")),
        ("i paid", ParsedCommand(kind=CommandKind.PAID, sku=None, loan_id=None, raw="i paid")),
    ],
)
def test_exact_commands(text: str, expected: ParsedCommand) -> None:
    assert parse_command(text) == expected


@pytest.mark.parametrize(
    ("text", "sku"),
    [
        ("NEED USB-C", "usbc_charger"),
        ("NEED USBC", "usbc_charger"),
        ("NEED USB C", "usbc_charger"),
        ("NEED USB - C", "usbc_charger"),
        ("NEED USB- C", "usbc_charger"),
        ("NEED USB -C", "usbc_charger"),
        ("NEED CHARGER", "usbc_charger"),
        ("NEED   USB-C", "usbc_charger"),
        ("needing a usb c", "usbc_charger"),
        ("he's needing USB C", "usbc_charger"),
        ("he's needing USB - C", "usbc_charger"),
        ("NEED LIGHTNING", "lightning_cable"),
        ("NEED HDMI", "hdmi"),
        ("NEED DONGLE", "usbc_hub"),
        ("NEED HUB", "usbc_hub"),
    ],
)
def test_need_with_sku(text: str, sku: str) -> None:
    result = parse_command(text)
    assert result == ParsedCommand(kind=CommandKind.NEED, sku=sku, loan_id=None, raw=text)


def test_need_natural_language_hdmi() -> None:
    text = "need an hdmi for the projector"
    result = parse_command(text)
    assert result == ParsedCommand(
        kind=CommandKind.NEED, sku="hdmi", loan_id=None, raw=text
    )


def test_unknown_command() -> None:
    text = "asdf"
    result = parse_command(text)
    assert result == ParsedCommand(
        kind=CommandKind.UNKNOWN, sku=None, loan_id=None, raw=text
    )
