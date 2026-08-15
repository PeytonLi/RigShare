"""PRD 5.1: LEND creates a pending item; only YES makes it borrowable."""

from __future__ import annotations

from sqlalchemy import select

from app.loans import handle_inbound
from app.models import Item, Loan

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


def _lend(db, _fake_linq) -> Item:
    handle_inbound(db, _message("LEND HDMI", LENDER, "chat_lender", "e_lend"))
    db.flush()
    return db.execute(select(Item)).scalars().one()


def test_lend_asks_for_confirmation(db, _fake_linq):
    item = _lend(db, _fake_linq)
    assert item.status == "pending"
    assert "Reply YES to list it" in _fake_linq.texts[-1][1]


def test_unconfirmed_item_cannot_be_borrowed(db, _fake_linq):
    _lend(db, _fake_linq)
    handle_inbound(db, _message("NEED HDMI", BORROWER, "chat_borrower", "e_need"))
    db.flush()
    assert db.execute(select(Loan)).scalars().first() is None
    assert "Nothing listed" in _fake_linq.texts[-1][1]


def test_yes_lists_it_and_then_it_is_borrowable(db, _fake_linq):
    _lend(db, _fake_linq)
    handle_inbound(db, _message("YES", LENDER, "chat_lender", "e_yes"))
    db.flush()
    assert db.execute(select(Item)).scalars().one().status == "listed"

    handle_inbound(db, _message("NEED HDMI", BORROWER, "chat_borrower", "e_need"))
    db.flush()
    loan = db.execute(select(Loan)).scalars().one()
    assert loan.state == "matching"
    assert db.execute(select(Item)).scalars().one().status == "listed"
    assert any("Looking for a hdmi nearby" in text for _, text in _fake_linq.texts)


def test_yes_with_nothing_pending_says_so(db, _fake_linq):
    handle_inbound(db, _message("YES", LENDER, "chat_lender", "e_yes"))
    assert "Nothing waiting to be listed" in _fake_linq.texts[-1][1]


def test_yes_confirms_only_the_senders_own_listing(db, _fake_linq):
    _lend(db, _fake_linq)
    # A borrower texting YES must not list someone else's pending item.
    handle_inbound(db, _message("YES", BORROWER, "chat_borrower", "e_yes"))
    db.flush()
    assert db.execute(select(Item)).scalars().one().status == "pending"
