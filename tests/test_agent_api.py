from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent_api import (
    AgentApiError,
    apply_clerk_forfeit,
    apply_condition_verdict,
    hire_inspector,
    pick_item,
)
from app.inspect import run_inspect_return, run_quote_and_charge
from app.loans import handle_inbound
from app.models import Item, Loan, get_or_create_user
from app.superserve_client import BLOCK_METRIC, FakeSuperserve, set_superserve_gateway
from app.terac_client import FakeTerac, set_terac_gateway


def _seed_listed(db: Session) -> Item:
    lender = get_or_create_user(db, "+14159909839")
    item = Item(
        id=uuid.uuid4().hex,
        sku="hdmi",
        title="hdmi",
        lender_user_id=lender.id,
        status="listed",
        deposit_cents=1500,
        rental_cents=300,
        platform_fee_cents=200,
        lender_chat_id="chat_l",
    )
    db.add(item)
    db.commit()
    return item


def _matching_loan(db: Session, item: Item) -> Loan:
    borrower = get_or_create_user(db, "+17034051525")
    loan = Loan(
        id=uuid.uuid4().hex,
        item_id=item.id,
        borrower_user_id=borrower.id,
        lender_user_id=item.lender_user_id,
        state="matching",
        borrower_chat_id="chat_b",
        lender_chat_id=item.lender_chat_id,
        deposit_cents=item.deposit_cents,
        rental_cents=item.rental_cents,
        platform_fee_cents=item.platform_fee_cents,
    )
    db.add(loan)
    db.commit()
    return loan


def _inspecting_loan(db: Session, *, state: str = "inspecting") -> Loan:
    lender = get_or_create_user(db, "+14159909839")
    borrower = get_or_create_user(db, "+17034051525")
    item = Item(
        id=uuid.uuid4().hex,
        sku="hdmi",
        title="hdmi",
        lender_user_id=lender.id,
        status="out",
        deposit_cents=1500,
        rental_cents=300,
        platform_fee_cents=200,
        outbound_media_id="m_out",
    )
    loan = Loan(
        id=uuid.uuid4().hex,
        item_id=item.id,
        borrower_user_id=borrower.id,
        lender_user_id=lender.id,
        state=state,
        borrower_chat_id="chat_b",
        lender_chat_id="chat_l",
        deposit_cents=1500,
        rental_cents=300,
        platform_fee_cents=200,
        stripe_payment_intent_id="pi_test",
        return_media_id="m_back",
        band_room_id="room_1",
    )
    db.add_all([item, loan])
    db.commit()
    return loan


def test_pick_item_reserves_and_sends_checkout(db: Session, _fake_linq) -> None:
    item = _seed_listed(db)
    loan = _matching_loan(db, item)
    pick_item(db, loan.id, item.id, "evt_pick", source="agent")
    db.commit()
    db.refresh(loan)
    db.refresh(item)
    assert loan.state == "awaiting_deposit"
    assert item.status == "reserved"
    assert loan.matcher_source == "agent"
    assert loan.linq_payment_request_id
    assert _fake_linq.links[-1][1] == "https://zero.linqapp.com/pay/test"
    assert any("reply PAID" in text for _, text in _fake_linq.texts)


def test_pick_item_is_idempotent(db: Session, _fake_linq) -> None:
    item = _seed_listed(db)
    loan = _matching_loan(db, item)
    first = pick_item(db, loan.id, item.id, "evt_same", source="agent")
    second = pick_item(db, loan.id, item.id, "evt_same", source="agent")
    db.commit()
    assert first.id == second.id
    assert first.linq_payment_request_id == second.linq_payment_request_id
    assert len(_fake_linq.links) == 1


def test_pick_item_409_after_walking(db: Session, _fake_linq) -> None:
    item = _seed_listed(db)
    loan = _matching_loan(db, item)
    pick_item(db, loan.id, item.id, "evt_pick", source="agent")
    loan.state = "walking"
    loan.stripe_payment_intent_id = "pi_walk"
    db.commit()
    try:
        pick_item(db, loan.id, item.id, "evt_late", source="agent")
        raise AssertionError("expected 409")
    except AgentApiError as exc:
        assert exc.status == 409


def test_timeout_pick_sets_source(db: Session, _fake_linq) -> None:
    item = _seed_listed(db)
    loan = _matching_loan(db, item)
    run_quote_and_charge(db, loan.id)
    db.commit()
    db.refresh(loan)
    db.refresh(item)
    assert loan.matcher_source == "timeout"
    assert loan.state == "awaiting_deposit"
    assert item.status == "reserved"


def test_condition_allow_writes_returning(db: Session, _fake_linq) -> None:
    loan = _inspecting_loan(db)
    apply_condition_verdict(db, loan.id, "ALLOW", "evt_allow", "tape matches")
    db.commit()
    db.refresh(loan)
    assert loan.condition_verdict == "ALLOW"
    assert loan.state == "returning"


def test_condition_blocked_does_not_open_terac(db: Session, _fake_linq) -> None:
    loan = _inspecting_loan(db)
    apply_condition_verdict(db, loan.id, "BLOCKED", "evt_block", "no tape")
    db.commit()
    db.refresh(loan)
    assert loan.condition_verdict == "BLOCKED"
    assert loan.state == "blocked"
    assert loan.terac_opportunity_id is None


def test_inspect_then_hire_opens_terac(db: Session, _fake_linq) -> None:
    loan = _inspecting_loan(db, state="returning")
    fake = FakeSuperserve(metric=BLOCK_METRIC + 1)
    set_superserve_gateway(fake)
    terac = FakeTerac()
    set_terac_gateway(terac)
    try:
        run_inspect_return(db, loan.id)
        db.commit()
        db.refresh(loan)
        assert loan.state == "blocked"
        assert loan.condition_verdict == "BLOCKED"
        assert loan.terac_opportunity_id is None
        hired = hire_inspector(db, loan.id, "evt_hire")
        db.commit()
    finally:
        set_superserve_gateway(None)
        set_terac_gateway(None)
    assert hired.state == "blocked"
    assert hired.terac_hired_at is not None
    assert hired.terac_opportunity_id == f"opp_{loan.id}"


def test_hire_inspector_409_unless_blocked(db: Session) -> None:
    loan = _inspecting_loan(db)
    try:
        hire_inspector(db, loan.id, "evt_hire")
        raise AssertionError("expected 409")
    except AgentApiError as exc:
        assert exc.status == 409


def test_sms_settle_does_not_refund(db: Session, _fake_linq) -> None:
    item = _seed_listed(db)
    handle_inbound(
        db,
        {
            "event_id": "e_need",
            "event_type": "message.received",
            "data": {
                "chat": {"id": "chat_b"},
                "sender_handle": {"handle": "+17034051525"},
                "parts": [{"type": "text", "value": "NEED HDMI"}],
            },
        },
    )
    db.flush()
    loan = db.execute(select(Loan)).scalars().one()
    handle_inbound(
        db,
        {
            "event_id": "e_settle",
            "event_type": "message.received",
            "data": {
                "chat": {"id": "chat_l"},
                "sender_handle": {"handle": "+14159909839"},
                "parts": [{"type": "text", "value": f"SETTLE {loan.id}"}],
            },
        },
    )
    db.flush()
    db.refresh(loan)
    assert loan.stripe_refund_id is None
    assert loan.state == "matching"
    assert any("Clerk has to SETTLE" in text for _, text in _fake_linq.texts)


def test_clerk_forfeit_retires_item(db: Session) -> None:
    loan = _inspecting_loan(db, state="blocked")
    apply_clerk_forfeit(db, loan.id, "evt_forfeit")
    db.commit()
    db.refresh(loan)
    item = db.get(Item, loan.item_id)
    assert loan.terac_verdict == "different"
    assert item.status == "retired"


def test_internal_routes_reject_bad_secret(client, db: Session) -> None:
    item = _seed_listed(db)
    loan = _matching_loan(db, item)
    bad = client.post(
        "/internal/pick-item",
        headers={"X-Internal-Secret": "wrong"},
        json={"loan_id": loan.id, "item_id": item.id, "event_id": "evt"},
    )
    assert bad.status_code == 401
