"""Regressions for two bugs that stalled loans silently.

1. "Got it!" with punctuation parsed as UNKNOWN, so the loan never advanced.
2. GOT IT sent before payment.succeeded landed was recorded but never applied,
   leaving the loan stuck in `walking` with both timestamps already set.
"""

from __future__ import annotations

import uuid

import pytest

from app.commands import CommandKind, parse_command
from app.loans import handle_inbound, handle_payment_succeeded
from app.models import Item, Loan, User

LENDER = "+14159909839"
BORROWER = "+17034051525"


def _message(text: str, phone: str, chat_id: str, event_id: str = "evt") -> dict:
    return {
        "event_id": event_id,
        "event_type": "message.received",
        "data": {
            "chat": {"id": chat_id},
            "sender_handle": {"handle": phone},
            "parts": [{"type": "text", "value": text}],
        },
    }


def _paid(loan_id: str, pi: str | None = "pi_test") -> dict:
    return {
        "event_id": "evt_paid",
        "event_type": "payment.succeeded",
        "data": {
            "id": "pr_test",
            "metadata": {"loan_id": loan_id},
            "stripe": {"payment_intent_id": pi} if pi else {},
        },
    }


def _seed(db, state: str = "awaiting_deposit") -> Loan:
    borrower = User(id=uuid.uuid4().hex, phone=BORROWER)
    lender = User(id=uuid.uuid4().hex, phone=LENDER)
    item = Item(
        id=uuid.uuid4().hex, sku="hdmi", title="hdmi", lender_user_id=lender.id,
        status="reserved", deposit_cents=1500, rental_cents=300,
        platform_fee_cents=200, lender_chat_id="chat_lender",
    )
    loan = Loan(
        id=uuid.uuid4().hex, item_id=item.id, borrower_user_id=borrower.id,
        lender_user_id=lender.id, state=state, borrower_chat_id="chat_borrower",
        lender_chat_id="chat_lender", deposit_cents=1500, rental_cents=300,
        platform_fee_cents=200,
    )
    db.add_all([borrower, lender, item, loan])
    db.commit()
    return loan


@pytest.mark.parametrize(
    "text,expected",
    [
        ("GOT IT", CommandKind.GOT_IT),
        ("Got it!", CommandKind.GOT_IT),
        ("got it.", CommandKind.GOT_IT),
        ("GOT IT!!!", CommandKind.GOT_IT),
        ("returning!", CommandKind.RETURNING),
        ("Returning.", CommandKind.RETURNING),
        ("cancel!", CommandKind.CANCEL),
        ("LEND HDMI.", CommandKind.LEND),
    ],
)
def test_punctuation_does_not_break_commands(text: str, expected: str) -> None:
    assert parse_command(text).kind == expected


@pytest.mark.parametrize(
    "text,deposit,rental",
    [
        ("LEND HDMI $20", 2000, None),
        ("LEND HDMI $20.50", 2050, None),
        ("LEND HDMI $20.50 for $3.25", 2050, 325),
        ("lend hdmi $20.50.", 2050, None),
        ("LEND HDMI 6ft $20", 2000, None),
    ],
)
def test_decimal_prices_survive_normalization(text: str, deposit: int, rental: int | None) -> None:
    """Stripping '.' as punctuation turned $20.50 into a $2050.00 deposit."""
    cmd = parse_command(text)
    assert (cmd.deposit_cents, cmd.rental_cents) == (deposit, rental)


def test_got_it_before_payment_still_hands_off(db) -> None:
    loan = _seed(db)

    handle_inbound(db, _message("GOT IT", BORROWER, "chat_borrower", "e1"))
    handle_inbound(db, _message("Got it!", LENDER, "chat_lender", "e2"))
    db.flush()
    assert loan.state == "awaiting_deposit"
    assert loan.borrower_got_it_at and loan.lender_got_it_at

    handle_payment_succeeded(db, _paid(loan.id))
    db.flush()
    assert loan.state == "out"
    assert loan.return_by_at is not None


def test_payment_without_intent_does_not_advance(db) -> None:
    loan = _seed(db)
    handle_payment_succeeded(db, _paid(loan.id, pi=None))
    db.flush()
    # PRD 6: `walking` without stripe_payment_intent_id is an illegal transition.
    assert loan.state == "awaiting_deposit"
    assert loan.stripe_payment_intent_id is None


def test_returning_rejected_before_handoff(db, _fake_linq) -> None:
    loan = _seed(db)
    handle_inbound(db, _message("RETURNING", BORROWER, "chat_borrower", "e3"))
    db.flush()
    assert loan.state == "awaiting_deposit"


def test_lender_is_told_to_hand_over_on_payment(db, _fake_linq) -> None:
    loan = _seed(db)
    handle_payment_succeeded(db, _paid(loan.id))
    db.flush()
    assert any(chat == "chat_lender" for chat, _ in _fake_linq.texts)
