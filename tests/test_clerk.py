from __future__ import annotations

import uuid

import pytest
from sqlalchemy.orm import Session

from app import stripe_client
from app.clerk import Unauthorized, apply_clerk_settle, can_lender_settle, check_secret
from app.config import get_settings
from app.models import Item, Loan, get_or_create_user
from app.stripe_client import reset_stripe_fakes


def _make_loan(
    db: Session,
    *,
    stripe_pi: str | None = "pi_test",
    clerk_event_id: str | None = None,
    stripe_refund_id: str | None = None,
    item_status: str = "out",
) -> Loan:
    lender = get_or_create_user(db, "+14159909839")
    borrower = get_or_create_user(db, "+17034051525")
    db.flush()

    item = Item(
        id=uuid.uuid4().hex,
        sku="SKU-001",
        title="Test Item",
        lender_user_id=lender.id,
        deposit_cents=2500,
        rental_cents=500,
        platform_fee_cents=200,
        status=item_status,
    )
    db.add(item)
    db.flush()

    loan = Loan(
        id=uuid.uuid4().hex,
        item_id=item.id,
        borrower_user_id=borrower.id,
        lender_user_id=lender.id,
        deposit_cents=2500,
        rental_cents=500,
        platform_fee_cents=200,
        stripe_payment_intent_id=stripe_pi,
        clerk_settle_event_id=clerk_event_id,
        stripe_refund_id=stripe_refund_id,
        state="out",
    )
    db.add(loan)
    db.commit()
    return loan


def test_check_secret_bad_raises() -> None:
    with pytest.raises(Unauthorized):
        check_secret("wrong-secret")


def test_check_secret_good() -> None:
    check_secret("test-settle")


def test_apply_clerk_settle_refunds_once(db: Session) -> None:
    reset_stripe_fakes()
    loan = _make_loan(db)

    result = apply_clerk_settle(db, loan.id, "evt_clerk_1")
    db.commit()

    assert result.stripe_refund_id == "re_test"
    assert result.state == "closed"
    assert result.clerk_settle_event_id == "evt_clerk_1"
    assert len(stripe_client._refunds) == 1

    item = db.get(Item, loan.item_id)
    assert item is not None
    assert item.status == "listed"

    result2 = apply_clerk_settle(db, loan.id, "evt_clerk_1")
    db.commit()

    assert len(stripe_client._refunds) == 1
    assert result2.stripe_refund_id == "re_test"
    assert result2.clerk_settle_event_id == "evt_clerk_1"


def test_can_lender_settle_true_when_not_required(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REQUIRE_CLERK_SETTLE", "false")
    get_settings.cache_clear()
    loan = _make_loan(db)

    assert can_lender_settle(loan) is True


def test_can_lender_settle_false_when_required_no_clerk_id(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("REQUIRE_CLERK_SETTLE", "true")
    get_settings.cache_clear()
    loan = _make_loan(db)

    assert can_lender_settle(loan) is False
