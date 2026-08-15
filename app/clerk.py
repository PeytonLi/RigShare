from __future__ import annotations

import hmac

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Item, Loan
from app.money import refund_cents
from app.stripe_client import refund_payment_intent


class Unauthorized(Exception):
    pass


def check_secret(provided: str | None) -> None:
    expected = get_settings().internal_settle_secret
    if not hmac.compare_digest(provided or "", expected):
        raise Unauthorized


def apply_clerk_settle(session: Session, loan_id: str, event_id: str) -> Loan:
    loan = session.get(Loan, loan_id)
    if loan is None:
        raise ValueError(f"loan not found: {loan_id}")

    if loan.clerk_settle_event_id is None:
        loan.clerk_settle_event_id = event_id

    if loan.stripe_refund_id:
        return loan

    if not loan.stripe_payment_intent_id:
        raise ValueError("no payment intent")

    amount = refund_cents(loan.deposit_cents, loan.rental_cents, loan.platform_fee_cents)
    refund_id = refund_payment_intent(
        loan.stripe_payment_intent_id,
        amount,
        idempotency_key=f"loan-settle-{loan.id}",
    )
    loan.stripe_refund_id = refund_id
    loan.state = "closed"
    item = session.get(Item, loan.item_id)
    if item is not None:
        item.status = "listed"
    return loan


def can_lender_settle(loan: Loan) -> bool:
    if get_settings().require_clerk_settle:
        return bool(loan.clerk_settle_event_id)
    return True
