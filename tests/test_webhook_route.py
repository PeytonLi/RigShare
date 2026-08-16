from __future__ import annotations

from sqlalchemy import select

from app.models import Item, Loan, ProcessedEvent
from app.stripe_client import reset_stripe_fakes
from tests.helpers import dumps, message_received_payload, sign_linq_body


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"ok": True, "service": "rigshare"}


def test_home_recovers_photos_from_stored_webhooks(client, db):
    from app.models import User, record_event
    from tests.helpers import message_received_payload

    lender = User(phone="+14159909839")
    borrower = User(phone="+17034051525")
    db.add_all([lender, borrower])
    db.flush()
    item = Item(
        id="item_photo",
        sku="hdmi",
        title="hdmi",
        lender_user_id=lender.id,
        status="out",
        deposit_cents=1500,
        rental_cents=300,
        platform_fee_cents=200,
    )
    loan = Loan(
        id="loan_photo",
        item_id=item.id,
        borrower_user_id=borrower.id,
        lender_user_id=lender.id,
        state="returning",
        deposit_cents=1500,
        rental_cents=300,
        platform_fee_cents=200,
    )
    db.add_all([item, loan])
    out = message_received_payload(text="", chat_id="chat_l", from_phone=lender.phone, event_id="evt_out")
    out["data"]["parts"] = [{"type": "media", "id": "media_out", "mime_type": "image/jpeg"}]
    back = message_received_payload(text="", chat_id="chat_b", from_phone=borrower.phone, event_id="evt_back")
    back["data"]["parts"] = [{"type": "media", "attachment_id": "media_back", "mime_type": "image/jpeg"}]
    record_event(db, "evt_out", "message.received", out)
    record_event(db, "evt_back", "message.received", back)
    db.commit()

    page = client.get("/")
    assert page.status_code == 200
    db.expire_all()
    assert db.get(Item, "item_photo").outbound_media_id == "media_out"
    assert db.get(Loan, "loan_photo").return_media_id == "media_back"
    assert b"/media/media_out" in page.content
    assert b"/media/media_back" in page.content


def test_recovery_keeps_photos_per_chat_not_phone_wide(client, db):
    """Two loans from the same borrower must each get their own return photo.

    The old recovery assigned the single most-recent photo that phone ever sent
    to every blank loan, so outbound and return showed the same wrong image.
    """
    from app.models import User, record_event

    lender = User(phone="+14159909839")
    borrower = User(phone="+17034051525")
    db.add_all([lender, borrower])
    db.flush()
    items = []
    loans = []
    for idx, (item_id, loan_id, chat) in enumerate(
        [("item_a", "loan_a", "chat_b_a"), ("item_b", "loan_b", "chat_b_b")]
    ):
        item = Item(
            id=item_id,
            sku="hdmi",
            title="hdmi",
            lender_user_id=lender.id,
            status="out",
            deposit_cents=1500,
            rental_cents=300,
            platform_fee_cents=200,
            lender_chat_id=f"chat_l_{idx}",
        )
        loan = Loan(
            id=loan_id,
            item_id=item.id,
            borrower_user_id=borrower.id,
            lender_user_id=lender.id,
            state="returning",
            borrower_chat_id=chat,
            deposit_cents=1500,
            rental_cents=300,
            platform_fee_cents=200,
        )
        db.add_all([item, loan])
        items.append(item)
        loans.append(loan)
    db.flush()

    # Same borrower, two chats, two distinct return photos -- newest first.
    back_a = message_received_payload(text="", chat_id="chat_b_a", from_phone=borrower.phone, event_id="evt_back_a")
    back_a["data"]["parts"] = [{"type": "media", "id": "media_back_a", "mime_type": "image/jpeg"}]
    back_b = message_received_payload(text="", chat_id="chat_b_b", from_phone=borrower.phone, event_id="evt_back_b")
    back_b["data"]["parts"] = [{"type": "media", "id": "media_back_b", "mime_type": "image/jpeg"}]
    record_event(db, "evt_back_a", "message.received", back_a)
    record_event(db, "evt_back_b", "message.received", back_b)
    db.commit()

    client.get("/")
    db.expire_all()
    assert db.get(Loan, "loan_a").return_media_id == "media_back_a"
    assert db.get(Loan, "loan_b").return_media_id == "media_back_b"
    assert db.get(Loan, "loan_a").return_media_id != db.get(Loan, "loan_b").return_media_id


def test_home_lists_empty(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"RigShare" in response.content
    assert b"live.js" in response.content
    assert b'id="live-chip"' in response.content


def test_live_rev_moves_when_inventory_does(client, db):
    first = client.get("/live")
    assert first.status_code == 200
    assert first.json()["ok"] is True
    rev = first.json()["rev"]
    assert rev

    from app.models import Item, User

    user = User(phone="+14159909839")
    db.add(user)
    db.flush()
    db.add(
        Item(
            id="item_live",
            sku="hdmi",
            title="hdmi",
            lender_user_id=user.id,
            status="listed",
            deposit_cents=1500,
            rental_cents=300,
            platform_fee_cents=200,
        )
    )
    db.commit()
    assert client.get("/live").json()["rev"] != rev


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
    item = db.execute(select(Item)).scalar_one()
    assert loan.state == "matching"
    assert item.status == "listed"
    assert any("Looking for a hdmi nearby" in text for _, text in _fake_linq.texts)
    assert not _fake_linq.links

    picked = client.post(
        "/internal/pick-item",
        headers={"X-Internal-Secret": "test-settle"},
        json={"loan_id": loan.id, "item_id": item.id, "event_id": "evt_pick"},
    )
    assert picked.status_code == 200
    db.expire_all()
    loan = db.get(Loan, loan.id)
    item = db.get(Item, item.id)
    assert loan.state == "awaiting_deposit"
    assert item.status == "reserved"
    assert loan.matcher_source == "agent"
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
    assert loan.state == "out" or loan.state == "returning"
    assert loan.stripe_refund_id is None
    assert any("Clerk has to SETTLE" in text for _, text in _fake_linq.texts)

    ok = client.post(
        "/internal/clerk-settle",
        headers={"X-Internal-Secret": "test-settle"},
        json={"loan_id": loan.id, "event_id": "evt_clerk"},
    )
    assert ok.status_code == 200
    db.expire_all()
    loan = db.get(Loan, loan.id)
    assert loan.state == "closed"
    assert loan.stripe_refund_id == "re_test"
    page = client.get(f"/loans/{loan.id}")
    assert page.status_code == 200
    assert b"closed" in page.content
    assert b"Agents" in page.content


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
