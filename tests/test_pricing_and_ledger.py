"""Lender-set prices, the item-value cap, and what we owe the lender."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.clerk import settle_loan
from app.commands import parse_command
from app.loans import handle_inbound
from app.models import Item, Loan, User
from app.money import PriceRejected, quote
from app.skus import prohibited_item
from app.stripe_client import reset_stripe_fakes

LENDER = "+14159909839"
STRANGER = "+15105550123"


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


def test_prices_parse_out_of_the_lend_text():
    assert parse_command("LEND HDMI 20").deposit_cents == 2000
    assert parse_command("LEND HDMI $20 for $3").rental_cents == 300
    # Specs are not money.
    assert parse_command("LEND HDMI 6ft").deposit_cents is None
    assert parse_command("LEND usb-c charger 100w").deposit_cents is None


def test_lender_price_beats_the_sku_table(db, _fake_linq):
    handle_inbound(db, _message("LEND HDMI $20 for $3", LENDER, "chat_l"))
    db.flush()
    item = db.execute(select(Item)).scalars().one()
    assert (item.deposit_cents, item.rental_cents) == (2000, 300)
    assert "$20 hold" in _fake_linq.texts[-1][1]


def test_deposit_over_the_cap_is_refused(db, _fake_linq):
    handle_inbound(db, _message("LEND HDMI $200", LENDER, "chat_l"))
    db.flush()
    assert db.execute(select(Item)).scalars().first() is None
    assert "cap" in _fake_linq.texts[-1][1]


def test_price_that_leaves_nothing_to_refund_is_refused(db, _fake_linq):
    handle_inbound(db, _message("LEND HDMI $5 for $5", LENDER, "chat_l"))
    db.flush()
    assert db.execute(select(Item)).scalars().first() is None
    assert "refund" in _fake_linq.texts[-1][1]


def test_prohibited_items_are_refused(db, _fake_linq):
    assert prohibited_item("lend my macbook") == "macbook"
    # The accessory is the product; what it plugs into is not.
    assert prohibited_item("laptop charger, orange tape") is None

    handle_inbound(db, _message("LEND my iphone", LENDER, "chat_l"))
    db.flush()
    assert db.execute(select(Item)).scalars().first() is None
    assert "cheap gear people forget" in _fake_linq.texts[-1][1]


def test_quote_rejects_bad_overrides():
    with pytest.raises(PriceRejected):
        quote("hdmi", deposit_cents=20_000)
    with pytest.raises(PriceRejected):
        quote("hdmi", deposit_cents=10)


def _loan(db, lender_phone: str) -> Loan:
    lender = User(id=uuid.uuid4().hex, phone=lender_phone)
    borrower = User(id=uuid.uuid4().hex, phone="+17034051525")
    item = Item(
        id=uuid.uuid4().hex, sku="hdmi", title="hdmi", lender_user_id=lender.id,
        status="out", deposit_cents=1500, rental_cents=300, platform_fee_cents=200,
    )
    loan = Loan(
        id=uuid.uuid4().hex, item_id=item.id, borrower_user_id=borrower.id,
        lender_user_id=lender.id, state="inspecting", deposit_cents=1500,
        rental_cents=300, platform_fee_cents=200, stripe_payment_intent_id="pi_test",
    )
    db.add_all([lender, borrower, item, loan])
    db.commit()
    return loan


def test_third_party_lender_is_owed_the_rental(db):
    reset_stripe_fakes()
    loan = _loan(db, STRANGER)
    assert settle_loan(db, loan) == 1000
    assert loan.lender_payout_cents == 300
    assert loan.lender_paid_at is None  # a real debt, pay it by hand


def test_our_own_listing_owes_nobody(db):
    reset_stripe_fakes()
    loan = _loan(db, LENDER)
    settle_loan(db, loan)
    assert loan.lender_payout_cents == 300
    assert loan.lender_paid_at is not None


def test_overdue_sweep_chases_once_and_never_forfeits(db, _fake_linq):
    from datetime import timedelta

    import workflows.tasks as tasks
    from app.models import utcnow

    sweep = tasks.sweepOverdue._func
    loan = _loan(db, LENDER)
    loan.state = "out"
    loan.borrower_chat_id = "chat_b"
    loan.return_by_at = utcnow() - timedelta(hours=3)  # past due + 2h grace
    db.commit()

    assert sweep()["chased"] == [loan.id]
    assert "past due" in _fake_linq.texts[-1][1]
    db.expire_all()
    assert db.get(Loan, loan.id).state == "out"  # a deposit is never kept by a cron
    assert sweep()["chased"] == []  # nagged once, not every tick
