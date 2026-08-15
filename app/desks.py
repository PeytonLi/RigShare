"""What each company desk last did. Dashboard reads this, not Band prompts."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DeskEvent, Item, Loan
from app.product import load_state, tally


def record_desk(session: Session, desk: str, detail: str) -> None:
    import uuid

    session.add(
        DeskEvent(
            id=uuid.uuid4().hex,
            desk=desk,
            detail=detail[:280],
        )
    )


def _latest(session: Session, desk: str) -> str | None:
    row = session.execute(
        select(DeskEvent)
        .where(DeskEvent.desk == desk)
        .order_by(DeskEvent.created_at.desc())
    ).scalars().first()
    return row.detail if row is not None else None


def company_desks(session: Session) -> list[dict[str, str]]:
    state = load_state()
    votes = tally(session)
    last_loan = session.execute(select(Loan).order_by(Loan.created_at.desc())).scalars().first()
    last_item = session.execute(select(Item).order_by(Item.created_at.desc())).scalars().first()

    sales = _latest(session, "sales")
    if sales is None and last_item is not None:
        sales = f"listed {last_item.sku}"
    ops = _latest(session, "ops")
    if ops is None and last_loan is not None:
        ops = last_loan.state
    finance = _latest(session, "finance")
    if finance is None:
        finance = "Clerk settles clean returns. Lender is not in the loop."
        if last_loan is not None and last_loan.stripe_refund_id:
            finance = f"refunded {last_loan.stripe_refund_id}"
    counsel = _latest(session, "counsel") or "laptops, phones, anything over $80: refused"

    growth = state.growth_detail
    if not state.applied and votes["n"]:
        growth = f"{votes['n']} Terac responses waiting to apply"
    product = state.product_detail
    if not state.applied and votes["n"]:
        product = f"catalog votes in ({votes['n']}). apply to reorder the bag."

    return [
        {"name": "Growth", "who": "pitch vote", "detail": growth},
        {"name": "Product", "who": "catalog", "detail": product},
        {"name": "Sales", "who": "Matcher", "detail": sales or "waiting on a NEED"},
        {"name": "Ops", "who": "Condition", "detail": ops or "waiting on a return photo"},
        {"name": "Finance", "who": "Clerk", "detail": finance},
        {"name": "Counsel", "who": "refuse list", "detail": counsel},
    ]
