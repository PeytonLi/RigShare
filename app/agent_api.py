"""Signed agent verbs. Band tools POST here. ImageMagick and SMS do not write these."""

from __future__ import annotations

import json
import logging

from sqlalchemy.orm import Session

from app.catalog import sort_items
from app.linq_client import create_payment_request, send_link, send_text
from app.models import Item, Loan, record_event, utcnow
from app.money import refund_cents
from app.pioneer_client import compose_reply

log = logging.getLogger("rigshare")


class AgentApiError(Exception):
    def __init__(self, message: str, status: int = 409) -> None:
        self.status = status
        super().__init__(message)


def _dollars(cents: int) -> str:
    if cents % 100 == 0:
        return f"${cents // 100}"
    return f"${cents / 100:.2f}"


def _say(chat_id: str | None, fallback: str, template_key: str, slots: dict | None, loan: Loan) -> None:
    if not chat_id:
        return
    text, source = compose_reply(template_key, fallback, slots)
    send_text(chat_id, text)
    loan.copy_source = source


def _idempotent(session: Session, event_id: str, event_type: str, payload: dict) -> bool:
    """True if this event_id is new and should run."""
    _, created = record_event(session, event_id, event_type, payload)
    return created


def listed_candidates(session: Session, sku: str) -> list[Item]:
    from sqlalchemy import select

    items = session.execute(select(Item).where(Item.sku == sku, Item.status == "listed")).scalars().all()
    return sort_items(list(items))


def pick_item(
    session: Session,
    loan_id: str,
    item_id: str,
    event_id: str,
    *,
    source: str = "agent",
) -> Loan:
    loan = session.get(Loan, loan_id)
    if loan is None:
        raise AgentApiError("loan not found", 404)
    if loan.stripe_payment_intent_id or loan.state not in {"matching", "awaiting_deposit"}:
        raise AgentApiError("loan already past matching", 409)
    item = session.get(Item, item_id)
    if item is None:
        raise AgentApiError("item not found", 404)
    if item.status == "reserved" and loan.item_id != item.id:
        raise AgentApiError("item reserved for another loan", 409)
    if item.status not in {"listed", "reserved"}:
        raise AgentApiError("item not listed", 409)
    if not _idempotent(session, event_id, "agent.pick_item", {"loan_id": loan_id, "item_id": item_id}):
        return loan

    if loan.item_id != item.id:
        old = session.get(Item, loan.item_id)
        if old is not None and old.status == "reserved" and old.id != item.id:
            old.status = "listed"

    item.status = "reserved"
    loan.item_id = item.id
    loan.lender_user_id = item.lender_user_id
    loan.lender_chat_id = item.lender_chat_id
    loan.deposit_cents = item.deposit_cents
    loan.rental_cents = item.rental_cents
    loan.platform_fee_cents = item.platform_fee_cents
    loan.matcher_item_id = item.id
    loan.matcher_source = source
    loan.matched_at = utcnow()
    loan.state = "awaiting_deposit"

    if not loan.linq_payment_request_id:
        pay = create_payment_request(
            item.deposit_cents,
            f"RigShare hold {item.sku}",
            {"loan_id": loan.id},
        )
        loan.linq_payment_request_id = pay.id
        refund = refund_cents(item.deposit_cents, item.rental_cents, item.platform_fee_cents)
        from app.product import borrower_quote

        fallback = borrower_quote(
            item.title,
            item.deposit_cents,
            item.rental_cents,
            item.platform_fee_cents,
            refund,
        )
        _say(
            loan.borrower_chat_id,
            fallback,
            "need_quote",
            {
                "title": item.title,
                "deposit": _dollars(item.deposit_cents),
                "rental": _dollars(item.rental_cents),
                "fee": _dollars(item.platform_fee_cents),
                "refund": _dollars(refund),
            },
            loan,
        )
        if loan.borrower_chat_id:
            send_link(loan.borrower_chat_id, pay.checkout_url)
    return loan


def apply_condition_verdict(
    session: Session,
    loan_id: str,
    verdict: str,
    event_id: str,
    reason: str = "",
) -> Loan:
    label = verdict.strip().upper()
    if label not in {"ALLOW", "BLOCKED"}:
        raise AgentApiError("verdict must be ALLOW or BLOCKED", 400)
    loan = session.get(Loan, loan_id)
    if loan is None:
        raise AgentApiError("loan not found", 404)
    if loan.state not in {"inspecting", "returning", "blocked"}:
        raise AgentApiError(f"loan is {loan.state}, not inspecting", 409)
    if not _idempotent(
        session, event_id, "agent.condition_verdict", {"loan_id": loan_id, "verdict": label}
    ):
        return loan

    from app.band_client import post_room_message
    from app.config import get_settings

    loan.condition_verdict = label
    loan.condition_event_id = event_id
    loan.condition_at = utcnow()
    settings = get_settings()

    if label == "ALLOW":
        loan.state = "returning"
        from app.desks import record_desk

        record_desk(session, "ops", f"ALLOW {loan.id[:8]}")
        _say(
            loan.lender_chat_id,
            "Condition ALLOW. Clerk is settling. You do not need to reply SETTLE.",
            "condition_allow",
            {"loan_id": loan.id, "reason": reason},
            loan,
        )
        if loan.band_room_id:
            post_room_message(
                loan.band_room_id,
                f"ALLOW loan_id={loan.id} compare_metric={loan.compare_metric}. {reason} Clerk: settle now. Do not wait for the lender.",
                mention_agent_id=settings.band_clerk_agent_id or None,
                mention_handle="Clerk",
            )
        return loan

    loan.state = "blocked"
    from app.desks import record_desk

    record_desk(session, "ops", f"BLOCKED {loan.id[:8]}")
    _say(
        loan.borrower_chat_id,
        "Return doesn't match the outbound photo (missing orange tape). "
        "Deposit stays held. Lender is looking at it.",
        "condition_blocked",
        {"loan_id": loan.id, "reason": reason},
        loan,
    )
    if loan.band_room_id:
        post_room_message(
            loan.band_room_id,
            f"BLOCKED loan_id={loan.id} compare_metric={loan.compare_metric}. {reason} Clerk: hire_inspector.",
            mention_agent_id=settings.band_clerk_agent_id or None,
            mention_handle="Clerk",
        )
    return loan


def hire_inspector(session: Session, loan_id: str, event_id: str) -> Loan:
    loan = session.get(Loan, loan_id)
    if loan is None:
        raise AgentApiError("loan not found", 404)
    if loan.state != "blocked":
        raise AgentApiError("hire_inspector only after Condition BLOCKED", 409)
    if not _idempotent(session, event_id, "agent.hire_inspector", {"loan_id": loan_id}):
        return loan
    from app.inspect import run_open_dispute

    run_open_dispute(session, loan.id)
    loan.terac_hired_at = utcnow()
    return loan


def apply_clerk_forfeit(session: Session, loan_id: str, event_id: str) -> Loan:
    loan = session.get(Loan, loan_id)
    if loan is None:
        raise AgentApiError("loan not found", 404)
    if not _idempotent(session, event_id, "agent.clerk_forfeit", {"loan_id": loan_id}):
        return loan
    from app.disputes import apply_forfeit

    apply_forfeit(session, loan)
    return loan


def persist_entities(loan: Loan, entities: dict[str, str] | None) -> None:
    if entities:
        loan.pioneer_entities_json = json.dumps(entities)
