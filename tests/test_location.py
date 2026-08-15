from __future__ import annotations

import pytest

from app.linq_client import download_media, get_location
from app.models import Item, Loan, get_or_create_user
from tests.helpers import dumps, sign_linq_body


def location_payload(chat_id: str, event_id: str = "evt_loc") -> dict:
    return {
        "api_version": "v3",
        "webhook_version": "2026-02-03",
        "event_type": "location.sharing.started",
        "event_id": event_id,
        "data": {"chat": {"id": chat_id, "is_group": False}},
    }


def post_location(client, chat_id: str, event_id: str = "evt_loc"):
    body = dumps(location_payload(chat_id, event_id))
    return client.post(
        "/webhooks/linq", content=body, headers=sign_linq_body(body, event_id=event_id)
    )


@pytest.fixture
def loan(db):
    lender = get_or_create_user(db, "+14159909839")
    borrower = get_or_create_user(db, "+17034051525")
    item = Item(
        id="item_loc",
        sku="hdmi",
        title="hdmi",
        lender_user_id=lender.id,
        status="out",
        deposit_cents=1500,
        rental_cents=300,
        platform_fee_cents=200,
        lender_chat_id="chat_l",
    )
    loan = Loan(
        id="loan_loc",
        item_id=item.id,
        borrower_user_id=borrower.id,
        lender_user_id=lender.id,
        state="walking",
        borrower_chat_id="chat_b",
        lender_chat_id="chat_l",
        deposit_cents=1500,
        rental_cents=300,
        platform_fee_cents=200,
        stripe_payment_intent_id="pi_loc",
    )
    db.add_all([item, loan])
    db.commit()
    return loan


def test_fake_gateway_supports_media_and_location(_fake_linq):
    _fake_linq.media["media_1"] = b"jpeg"
    _fake_linq.chat_locations["chat_b"] = (37.7749, -122.4194)
    assert download_media("media_1") == b"jpeg"
    assert download_media("missing") == b"fake-media-bytes"
    assert get_location("chat_b") == (37.7749, -122.4194)
    assert get_location("chat_nobody") is None


def test_sharing_texts_maps_link_to_other_party(client, db, loan, _fake_linq):
    _fake_linq.chat_locations["chat_b"] = (37.7749, -122.4194)
    assert post_location(client, "chat_b").status_code == 200
    assert _fake_linq.texts == [
        ("chat_l", "They're on the way: https://maps.google.com/?q=37.7749,-122.4194")
    ]


def test_lender_sharing_texts_borrower(client, db, loan, _fake_linq):
    _fake_linq.chat_locations["chat_l"] = (1.5, 2.5)
    assert post_location(client, "chat_l").status_code == 200
    assert _fake_linq.texts[0][0] == "chat_b"


def test_empty_location_sends_nothing(client, db, loan, _fake_linq):
    assert post_location(client, "chat_b").status_code == 200
    assert _fake_linq.texts == []


def test_loan_not_walking_sends_nothing(client, db, loan, _fake_linq):
    loan.state = "out"
    db.commit()
    _fake_linq.chat_locations["chat_b"] = (37.7749, -122.4194)
    assert post_location(client, "chat_b").status_code == 200
    assert _fake_linq.texts == []


def test_unknown_chat_sends_nothing(client, db, loan, _fake_linq):
    _fake_linq.chat_locations["chat_x"] = (37.7749, -122.4194)
    assert post_location(client, "chat_x").status_code == 200
    assert _fake_linq.texts == []


def test_location_never_advances_state(client, db, loan, _fake_linq):
    _fake_linq.chat_locations["chat_b"] = (37.7749, -122.4194)
    post_location(client, "chat_b")
    db.expire_all()
    assert db.get(Loan, "loan_loc").state == "walking"
