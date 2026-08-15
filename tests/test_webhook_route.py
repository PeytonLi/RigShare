from __future__ import annotations

from sqlalchemy import select

from app.models import Item, Loan, ProcessedEvent
from app.stripe_client import reset_stripe_fakes
from tests.helpers import dumps, message_received_payload, sign_linq_body


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"ok": True, "service": "rigshare"}


def test_home_lists_empty(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"RigShare" in response.content


def test_webhook_rejects_bad_signature(client):
    payload = message_received_payload(text="hello")
    body = dumps(payload)
    headers = sign_linq_body(body)
    headers["webhook-signature"] = "v1,AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
    response = client.post("/webhooks/linq", content=body, headers=headers)
    assert response.status_code == 401


def test_unknown_text_replies_live(client, db, _fake_linq):
    payload = message_received_payload(text="hello", chat_id="chat_b", from_phone="+17034051525")
    body = dumps(payload)
    response = client.post("/webhooks/linq", content=body, headers=sign_linq_body(body))
    assert response.status_code == 200
    assert _fake_linq.texts
    assert "RigShare is live" in _fake_linq.texts[0][1]
    assert db.get(ProcessedEvent, payload["event_id"]) is not None


def test_duplicate_event_does_not_double_reply(client, db, _fake_linq):
    payload = message_received_payload(text="hello", event_id="evt_dup")
    body = dumps(payload)
    headers = sign_linq_body(body, event_id="evt_dup")
    assert client.post("/webhooks/linq", content=body, headers=headers).status_code == 200
    assert client.post("/webhooks/linq", content=body, headers=headers).status_code == 200
    assert len(_fake_linq.texts) == 1
    assert len(db.execute(select(ProcessedEvent)).scalars().all()) == 1


def test_lend_need_pay_settle_loop(client, db, _fake_linq):
    reset_stripe_fakes()
    lend = message_received_payload(
        text="LEND HDMI",
        chat_id="chat_l",
        from_phone="+14159909839",
        event_id="evt_lend",
    )
    body = dumps(lend)
    assert client.post("/webhooks/linq", content=body, headers=sign_linq_body(body, event_id="evt_lend")).status_code == 200
    item = db.execute(select(Item)).scalar_one()
    assert item.sku == "hdmi"
    assert item.status == "pending"
    assert item.deposit_cents == 1500

    yes = message_received_payload(
        text="YES",
        chat_id="chat_l",
        from_phone="+14159909839",
        event_id="evt_yes",
    )
    body = dumps(yes)
    assert client.post("/webhooks/linq", content=body, headers=sign_linq_body(body, event_id="evt_yes")).status_code == 200
    db.expire_all()
    item = db.execute(select(Item)).scalar_one()
    assert item.status == "listed"

    need = message_received_payload(
        text="NEED HDMI",
        chat_id="chat_b",
        from_phone="+17034051525",
        event_id="evt_need",
    )
    body = dumps(need)
    assert client.post("/webhooks/linq", content=body, headers=sign_linq_body(body, event_id="evt_need")).status_code == 200
    db.expire_all()
    loan = db.execute(select(Loan)).scalar_one()
    assert loan.state == "awaiting_deposit"
    assert _fake_linq.links[-1][1] == "https://zero.linqapp.com/pay/test"
    assert any("$15 hold" in text for _, text in _fake_linq.texts)

    paid = {
        "api_version": "v3",
        "webhook_version": "2026-02-03",
        "event_type": "payment.succeeded",
        "event_id": "evt_pay",
        "data": {
            "id": "pr_test",
            "metadata": {"loan_id": loan.id},
            "stripe": {"payment_intent_id": "pi_test"},
        },
    }
    body = dumps(paid)
    assert client.post("/webhooks/linq", content=body, headers=sign_linq_body(body, event_id="evt_pay")).status_code == 200
    db.expire_all()
    loan = db.get(Loan, loan.id)
    assert loan.state == "walking"
    assert loan.stripe_payment_intent_id == "pi_test"

    for phone, chat, eid in (
        ("+17034051525", "chat_b", "evt_got_b"),
        ("+14159909839", "chat_l", "evt_got_l"),
    ):
        got = message_received_payload(text="GOT IT", chat_id=chat, from_phone=phone, event_id=eid)
        body = dumps(got)
        assert client.post("/webhooks/linq", content=body, headers=sign_linq_body(body, event_id=eid)).status_code == 200

    db.expire_all()
    loan = db.get(Loan, loan.id)
    assert loan.state == "out"

    returning = message_received_payload(
        text="RETURNING",
        chat_id="chat_b",
        from_phone="+17034051525",
        event_id="evt_ret",
    )
    body = dumps(returning)
    assert client.post("/webhooks/linq", content=body, headers=sign_linq_body(body, event_id="evt_ret")).status_code == 200

    settle = message_received_payload(
        text=f"SETTLE {loan.id}",
        chat_id="chat_l",
        from_phone="+14159909839",
        event_id="evt_settle",
    )
    body = dumps(settle)
    assert client.post("/webhooks/linq", content=body, headers=sign_linq_body(body, event_id="evt_settle")).status_code == 200
    db.expire_all()
    loan = db.get(Loan, loan.id)
    assert loan.state == "closed"
    assert loan.stripe_refund_id == "re_test"
    page = client.get(f"/loans/{loan.id}")
    assert page.status_code == 200
    assert b"closed" in page.content


def test_clerk_settle_endpoint(client, db):
    from app.models import Item, get_or_create_user

    lender = get_or_create_user(db, "+14159909839")
    borrower = get_or_create_user(db, "+17034051525")
    item = Item(
        id="item_clerk",
        sku="hdmi",
        title="hdmi",
        lender_user_id=lender.id,
        status="out",
        deposit_cents=1500,
        rental_cents=300,
        platform_fee_cents=200,
    )
    loan = Loan(
        id="loan_clerk",
        item_id=item.id,
        borrower_user_id=borrower.id,
        lender_user_id=lender.id,
        state="returning",
        deposit_cents=1500,
        rental_cents=300,
        platform_fee_cents=200,
        stripe_payment_intent_id="pi_clerk",
    )
    db.add_all([item, loan])
    db.commit()
    bad = client.post(
        "/internal/clerk-settle",
        headers={"X-Internal-Secret": "wrong"},
        json={"loan_id": "loan_clerk", "event_id": "evt_clerk"},
    )
    assert bad.status_code == 401
    ok = client.post(
        "/internal/clerk-settle",
        headers={"X-Internal-Secret": "test-settle"},
        json={"loan_id": "loan_clerk", "event_id": "evt_clerk"},
    )
    assert ok.status_code == 200
    db.expire_all()
    loan = db.get(Loan, "loan_clerk")
    assert loan.clerk_settle_event_id == "evt_clerk"
    assert loan.state == "closed"
    assert loan.stripe_refund_id == "re_test"
