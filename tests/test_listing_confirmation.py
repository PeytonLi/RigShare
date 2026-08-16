"""PRD 5.1: LEND creates a pending item; only YES makes it borrowable."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.loans import handle_inbound
from app.models import Item, Loan, User

LENDER = "+14159909839"
BORROWER = "+17034051525"


def _message(text: str, phone: str, chat_id: str, event_id: str = "evt", media_id: str | None = None) -> dict:
    parts: list[dict] = []
    if text:
        parts.append({"type": "text", "value": text})
    if media_id:
        parts.append({"type": "media", "id": media_id, "mime_type": "image/jpeg"})
    return {
        "event_id": event_id,
        "event_type": "message.received",
        "data": {
            "chat": {"id": chat_id},
            "sender_handle": {"handle": phone},
            "parts": parts,
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


def test_need_usb_c_with_space_or_dash_matches_listed_charger(db, _fake_linq):
    handle_inbound(db, _message("LEND USB-C", LENDER, "chat_lender", "e_lend"))
    handle_inbound(db, _message("YES", LENDER, "chat_lender", "e_yes"))
    db.flush()
    assert db.execute(select(Item)).scalars().one().sku == "usbc_charger"

    handle_inbound(db, _message("he's needing USB C", BORROWER, "chat_b1", "e_need_space"))
    db.flush()
    loan = db.execute(select(Loan)).scalars().one()
    assert loan.state == "matching"
    assert any("usbc charger" in text for _, text in _fake_linq.texts)


def test_bare_usbc_matches_listed_charger(db, _fake_linq):
    handle_inbound(db, _message("LEND USBC", LENDER, "chat_lender", "e_lend"))
    handle_inbound(db, _message("YES", LENDER, "chat_lender", "e_yes"))
    handle_inbound(db, _message("usbc", BORROWER, "chat_b1", "e_need_usbc"))
    db.flush()
    assert db.execute(select(Item)).scalars().one().sku == "usbc_charger"
    assert db.execute(select(Loan)).scalars().one().state == "matching"


def test_lend_keeps_a_photo_sent_in_the_same_text(db, _fake_linq):
    handle_inbound(db, _message("LEND HDMI", LENDER, "chat_lender", "e_lend", media_id="out_1"))
    db.flush()
    assert db.execute(select(Item)).scalars().one().outbound_media_id == "out_1"


def test_lend_uses_a_photo_sent_just_before(db, _fake_linq):
    handle_inbound(db, _message("", LENDER, "chat_lender", "e_pic", media_id="out_2"))
    handle_inbound(db, _message("LEND HDMI", LENDER, "chat_lender", "e_lend"))
    db.flush()
    assert db.execute(select(Item)).scalars().one().outbound_media_id == "out_2"


def test_photo_after_lend_fills_the_listing(db, _fake_linq):
    handle_inbound(db, _message("LEND HDMI", LENDER, "chat_lender", "e_lend"))
    handle_inbound(db, _message("", LENDER, "chat_lender", "e_pic", media_id="out_3"))
    db.flush()
    assert db.execute(select(Item)).scalars().one().outbound_media_id == "out_3"


def _out_loan(db) -> Loan:
    lender = User(id=uuid.uuid4().hex, phone=LENDER)
    borrower = User(id=uuid.uuid4().hex, phone=BORROWER)
    item = Item(
        id=uuid.uuid4().hex,
        sku="hdmi",
        title="hdmi",
        lender_user_id=lender.id,
        status="out",
        deposit_cents=1500,
        rental_cents=300,
        platform_fee_cents=200,
        lender_chat_id="chat_lender",
    )
    loan = Loan(
        id=uuid.uuid4().hex,
        item_id=item.id,
        borrower_user_id=borrower.id,
        lender_user_id=lender.id,
        state="out",
        borrower_chat_id="chat_borrower",
        lender_chat_id="chat_lender",
        deposit_cents=1500,
        rental_cents=300,
        platform_fee_cents=200,
        stripe_payment_intent_id="pi_photo",
    )
    db.add_all([lender, borrower, item, loan])
    db.commit()
    return loan


def test_returning_uses_a_photo_sent_just_before(db, _fake_linq):
    loan = _out_loan(db)
    handle_inbound(db, _message("", BORROWER, "chat_borrower", "e_pic", media_id="ret_1"))
    handle_inbound(db, _message("RETURNING", BORROWER, "chat_borrower", "e_ret"))
    db.flush()
    db.refresh(loan)
    assert loan.return_media_id == "ret_1"
    assert loan.state == "returning"


def test_photo_after_returning_fills_the_loan(db, _fake_linq):
    loan = _out_loan(db)
    handle_inbound(db, _message("RETURNING", BORROWER, "chat_borrower", "e_ret"))
    handle_inbound(db, _message("", BORROWER, "chat_borrower", "e_pic", media_id="ret_2"))
    db.flush()
    db.refresh(loan)
    assert loan.return_media_id == "ret_2"
