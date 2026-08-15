from __future__ import annotations

import hmac

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Item, Loan, utcnow
from app.money import refund_cents
from app.stripe_client import refund_payment_intent


class Unauthorized(Exception):
    pass


def check_secret(provided: str | None) -> None:
    expected = get_settings().internal_settle_secret
    if not hmac.compare_digest(provided or "", expected):
        raise Unauthorized


def settle_amount_cents(loan: Loan) -> int:
    if loan.manual_refund_cents is not None:
        return loan.manual_refund_cents
    return refund_cents(loan.deposit_cents, loan.rental_cents, loan.platform_fee_cents)


def settle_loan(session: Session, loan: Loan) -> int:
    """Refund, close, and book what the lender is owed. The only refund path.

    Every caller (Clerk HTTP, lender SMS, the settle workflow) comes through here so
    the gates and the ledger cannot drift apart the way two copies did.
    """
    from app.disputes import can_settle_after_dispute

    # PRD 7.5 delete test: a BLOCKED loan stays stuck until a human decided.
    if not can_settle_after_dispute(loan):
        raise ValueError("blocked: needs a Terac verdict or a lender override")
    if loan.stripe_refund_id:
        return settle_amount_cents(loan)
    if not loan.stripe_payment_intent_id:
        raise ValueError("no payment intent")

    amount = settle_amount_cents(loan)
    loan.stripe_refund_id = refund_payment_intent(
        loan.stripe_payment_intent_id,
        amount,
        idempotency_key=f"loan-settle-{loan.id}",
    )
    loan.state = "closed"
    item = session.get(Item, loan.item_id)
    if item is not None:
        item.status = "listed"
    _book_lender_payout(session, loan)
    return amount


def _book_lender_payout(session: Session, loan: Loan) -> None:
    """PRD 4.1: rental is owed to the lender. Venmo unless the lender is us."""
    from app.models import User

    loan.lender_payout_cents = loan.rental_cents
    lender = session.get(User, loan.lender_user_id)
    if lender is not None and lender.phone == get_settings().lender_phone:
        # We are the vendor: paying ourselves is a no-op, not a debt.
        loan.lender_paid_at = utcnow()


def apply_clerk_settle(session: Session, loan_id: str, event_id: str) -> Loan:
    loan = session.get(Loan, loan_id)
    if loan is None:
        raise ValueError(f"loan not found: {loan_id}")
    if loan.clerk_settle_event_id is None:
        loan.clerk_settle_event_id = event_id
    settle_loan(session, loan)
    return loan


def can_lender_settle(loan: Loan) -> bool:
    from app.disputes import can_settle_after_dispute

    if not can_settle_after_dispute(loan):
        return False
    if get_settings().require_clerk_settle:
        return bool(loan.clerk_settle_event_id)
    return True
