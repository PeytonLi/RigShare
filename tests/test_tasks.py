"""The Band delete test, at the workflow layer: no Clerk SETTLE id => no refund."""

from __future__ import annotations

import uuid

from app.models import Item, Loan, get_or_create_user
from app.stripe_client import reset_stripe_fakes
import workflows.tasks as tasks

# render_sdk wraps @app.task in a TaskCallable that dispatches to the Workflows
# service when called. Tests want the body.
settle = tasks.settle._func
forfeit = tasks.forfeit._func


def _loan(db, **overrides) -> Loan:
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
    )
    db.add(item)
    loan = Loan(
        id=uuid.uuid4().hex,
        item_id=item.id,
        borrower_user_id=borrower.id,
        lender_user_id=lender.id,
        state="inspecting",
        borrower_chat_id="chat_b",
        lender_chat_id="chat_l",
        deposit_cents=1500,
        rental_cents=300,
        platform_fee_cents=200,
        stripe_payment_intent_id="pi_test",
        **overrides,
    )
    db.add(loan)
    db.commit()
    return loan


def test_settle_refuses_without_clerk_event(db):
    reset_stripe_fakes()
    loan = _loan(db)
    result = settle(loan.id)
    assert result["ok"] is False
    assert "clerk_settle_event_id" in result["error"]
    db.expire_all()
    assert db.get(Loan, loan.id).stripe_refund_id is None


def test_settle_refunds_with_clerk_event(db):
    reset_stripe_fakes()
    loan = _loan(db, clerk_settle_event_id="evt_clerk")
    result = settle(loan.id)
    assert result["ok"] is True
    assert result["refund_id"] == "re_test"
    db.expire_all()
    closed = db.get(Loan, loan.id)
    assert closed.state == "closed"
    assert closed.stripe_refund_id == "re_test"


def test_settle_is_idempotent(db):
    reset_stripe_fakes()
    loan = _loan(db, clerk_settle_event_id="evt_clerk")
    first = settle(loan.id)
    second = settle(loan.id)
    assert second["refund_id"] == first["refund_id"]
    assert second["note"] == "already refunded"


def test_forfeit_keeps_deposit_and_retires_item(db):
    reset_stripe_fakes()
    loan = _loan(db)
    result = forfeit(loan.id)
    assert result["ok"] is True
    db.expire_all()
    forfeited = db.get(Loan, loan.id)
    assert forfeited.state == "forfeited"
    assert forfeited.stripe_refund_id is None
    assert db.get(Item, forfeited.item_id).status == "retired"


def test_forfeit_refuses_after_refund(db):
    reset_stripe_fakes()
    loan = _loan(db, stripe_refund_id="re_test")
    assert forfeit(loan.id)["ok"] is False
