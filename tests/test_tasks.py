"""The Band delete test, at the workflow layer: no Clerk SETTLE id => no refund."""

from __future__ import annotations

import uuid

import pytest

from app.models import Item, Loan, get_or_create_user
from app.stripe_client import reset_stripe_fakes
from app.terac_client import FakeTerac, set_terac_gateway
import workflows.tasks as tasks

# render_sdk wraps @app.task in a TaskCallable that dispatches to the Workflows
# service when called. Tests want the body.
settle = tasks.settle._func
forfeit = tasks.forfeit._func
onTeracSubmission = tasks.onTeracSubmission._func


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
    overrides.setdefault("state", "inspecting")
    loan = Loan(
        id=uuid.uuid4().hex,
        item_id=item.id,
        borrower_user_id=borrower.id,
        lender_user_id=lender.id,
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


def test_settle_refuses_blocked_loan_without_verdict(db):
    """PRD 7.5 delete test: pull Terac out and a disputed return stays stuck."""
    reset_stripe_fakes()
    loan = _loan(db, state="blocked", clerk_settle_event_id="evt_clerk")
    with pytest.raises(ValueError, match="blocked"):
        settle(loan.id)
    db.expire_all()
    assert db.get(Loan, loan.id).stripe_refund_id is None


def test_settle_allows_blocked_loan_after_verdict(db):
    reset_stripe_fakes()
    loan = _loan(
        db,
        state="blocked",
        clerk_settle_event_id="evt_clerk",
        terac_submission_id="sub_1",
        terac_verdict="damaged",
        manual_refund_cents=100,
    )
    assert settle(loan.id)["ok"] is True
    db.expire_all()
    assert db.get(Loan, loan.id).stripe_refund_id == "re_test"


def test_terac_submission_approves_and_pays_the_expert(db):
    fake = FakeTerac()
    fake.submissions["opp_1"] = [{"id": "sub_1"}]
    set_terac_gateway(fake)
    try:
        loan = _loan(db, state="blocked", terac_opportunity_id="opp_1", terac_verdict="fine")
        result = onTeracSubmission(loan.id)
        assert result["submission_id"] == "sub_1"
        assert fake.approved == ["sub_1"]
        db.expire_all()
        assert db.get(Loan, loan.id).terac_submission_id == "sub_1"
    finally:
        set_terac_gateway(None)


def test_terac_submission_pending_when_nobody_submitted(db):
    set_terac_gateway(FakeTerac())
    try:
        loan = _loan(db, state="blocked", terac_opportunity_id="opp_1")
        assert onTeracSubmission(loan.id)["pending"] is True
    finally:
        set_terac_gateway(None)
