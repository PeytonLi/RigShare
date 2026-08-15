from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.clerk import can_lender_settle
from app.commands import CommandKind, parse_command
from app.config import get_settings
from app.ingest import enrich_command
from app.linq_client import (
    create_payment_request,
    get_location,
    request_location,
    send_link,
    send_text,
)
from app.workflows_client import start_task
from app.linq_webhook import (
    event_id,
    event_type,
    inbound_chat_id,
    inbound_from_phone,
    inbound_media_ids,
    inbound_text,
)
from app.models import Item, Loan, get_or_create_user
from app.money import quote, refund_cents
from app.skus import SKUS, resolve_sku
from app.stripe_client import refund_payment_intent

log = logging.getLogger("rigshare")

LIVE_REPLY = "RigShare is live. LEND or NEED HDMI / USB-C / LIGHTNING."
ACTIVE_STATES = {
    "matching",
    "awaiting_deposit",
    "walking",
    "out",
    "returning",
    "inspecting",
    "settling",
    "blocked",
}


def _dollars(cents: int) -> str:
    if cents % 100 == 0:
        return f"${cents // 100}"
    return f"${cents / 100:.2f}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def handle_linq_event(session: Session, event: dict) -> None:
    kind = event_type(event)
    if kind == "message.received":
        handle_inbound(session, event)
        return
    if kind == "payment.succeeded":
        handle_payment_succeeded(session, event)
        return
    if kind == "location.sharing.started":
        handle_location_sharing(session, event)
        return


def handle_location_sharing(session: Session, event: dict) -> None:
    """One maps pin to the other party when someone starts sharing during the walk.

    PRD 7.2: never infer GOT IT from GPS. Location is wow, not source of truth.
    """
    # ponytail: webhook-driven only, one pin per share event. PLAN Phase 7 also
    # wants a 2-3 min poll while `walking`, which needs a scheduler this app does
    # not have. Upgrade path: a Render Workflows cron task that calls
    # get_location() for every loan still in `walking`.
    chat_id = inbound_chat_id(event)
    if not chat_id:
        return
    loan = session.execute(
        select(Loan)
        .where(
            or_(Loan.borrower_chat_id == chat_id, Loan.lender_chat_id == chat_id),
            Loan.state == "walking",
        )
        .order_by(Loan.created_at.desc())
    ).scalars().first()
    if loan is None:
        return
    point = get_location(chat_id)
    if point is None:
        return
    other = loan.lender_chat_id if chat_id == loan.borrower_chat_id else loan.borrower_chat_id
    if not other or other == chat_id:
        return
    lat, lng = point
    send_text(other, f"They're on the way: https://maps.google.com/?q={lat},{lng}")


def handle_inbound(session: Session, event: dict) -> None:
    text = inbound_text(event) or ""
    chat_id = inbound_chat_id(event)
    phone = inbound_from_phone(event)
    if not chat_id or not phone:
        log.warning("inbound missing chat or phone event=%s", event_id(event))
        return

    user = get_or_create_user(session, phone)
    cmd = enrich_command(text, parse_command(text))
    media = inbound_media_ids(event)
    if cmd.kind == "UNSAFE":
        send_text(chat_id, "Can't help with that. If you need a cable, text NEED HDMI / USB-C / LIGHTNING.")
        return
    settings = get_settings()
    is_lender = phone == settings.lender_phone

    if cmd.kind == CommandKind.LEND:
        sku = cmd.sku or resolve_sku(text)
        if sku is None:
            send_text(chat_id, "What are you lending? Reply LEND HDMI, LEND USB-C, or LEND LIGHTNING. Orange tape on it.")
            return
        money = quote(sku, demo=settings.demo_mode)
        item = Item(
            id=uuid.uuid4().hex,
            sku=sku,
            title=sku.replace("_", " "),
            lender_user_id=user.id,
            status="listed",
            deposit_cents=money.deposit_cents,
            rental_cents=money.rental_cents,
            platform_fee_cents=money.platform_fee_cents,
            outbound_media_id=media[0] if media else None,
            lender_chat_id=chat_id,
        )
        session.add(item)
        session.flush()
        send_text(
            chat_id,
            f"Listed {item.title}. {_dollars(money.deposit_cents)} hold. "
            f"You get {_dollars(money.rental_cents)} when it comes back. "
            f"Borrower also pays a {_dollars(money.platform_fee_cents)} RigShare fee (not taken from you). "
            "Mark it with orange tape.",
        )
        return

    if cmd.kind == CommandKind.NEED:
        sku = cmd.sku
        if sku is None:
            send_text(chat_id, "What do you need? NEED HDMI, NEED USB-C, or NEED LIGHTNING.")
            return
        item = session.execute(
            select(Item).where(Item.sku == sku, Item.status == "listed")
        ).scalars().first()
        if item is None:
            send_text(chat_id, f"Nothing listed for {sku.replace('_', ' ')} yet. Ask someone to LEND.")
            return
        loan = Loan(
            id=uuid.uuid4().hex,
            item_id=item.id,
            borrower_user_id=user.id,
            lender_user_id=item.lender_user_id,
            state="awaiting_deposit",
            borrower_chat_id=chat_id,
            lender_chat_id=item.lender_chat_id,
            deposit_cents=item.deposit_cents,
            rental_cents=item.rental_cents,
            platform_fee_cents=item.platform_fee_cents,
        )
        item.status = "reserved"
        session.add(loan)
        session.flush()
        pay = create_payment_request(
            item.deposit_cents,
            f"RigShare hold {sku}",
            {"loan_id": loan.id},
        )
        loan.linq_payment_request_id = pay.id
        refund = refund_cents(item.deposit_cents, item.rental_cents, item.platform_fee_cents)
        send_text(
            chat_id,
            f"{item.title} nearby, marked with orange tape. "
            f"{_dollars(item.deposit_cents)} hold now. "
            f"{_dollars(item.rental_cents)} to the lender if you bring it back. "
            f"{_dollars(item.platform_fee_cents)} RigShare fee. "
            f"{_dollars(refund)} refunded.",
        )
        send_link(chat_id, pay.checkout_url)
        start_task("quoteAndCharge", loan.id)
        return

    if cmd.kind == CommandKind.GOT_IT:
        loan = _active_loan_for(session, user.id)
        if loan is None:
            send_text(chat_id, "No active loan. Text NEED HDMI / USB-C / LIGHTNING.")
            return
        if user.id == loan.borrower_user_id:
            loan.borrower_got_it_at = _now()
            loan.borrower_chat_id = chat_id
        if user.id == loan.lender_user_id:
            loan.lender_got_it_at = _now()
            loan.lender_chat_id = chat_id
        if _try_hand_off(loan):
            send_text(chat_id, "You have it. Return by 2 hours. Photo the orange tape and reply RETURNING.")
            other = loan.lender_chat_id if user.id == loan.borrower_user_id else loan.borrower_chat_id
            if other and other != chat_id:
                send_text(other, "Both said GOT IT. Loan is out.")
            start_task("onHandoff", loan.id)
        elif loan.state == "awaiting_deposit":
            send_text(chat_id, "GOT IT noted. Waiting on the deposit to clear.")
        else:
            send_text(chat_id, "GOT IT noted. Waiting on the other person.")
        return

    if cmd.kind == CommandKind.RETURNING:
        loan = _active_loan_for(session, user.id)
        if loan is None:
            send_text(chat_id, "No active loan to return.")
            return
        if loan.state not in {"out", "returning"}:
            send_text(chat_id, "That loan is not out yet. Both sides reply GOT IT first.")
            return
        loan.state = "returning"
        if media:
            loan.return_media_id = media[0]
        send_text(
            chat_id,
            f"Return photo in. Lender: reply SETTLE {loan.id} if it matches (orange tape).",
        )
        start_task("inspectReturn", loan.id)
        return

    if cmd.kind == CommandKind.SETTLE:
        if not is_lender:
            send_text(chat_id, "Only the lender can SETTLE.")
            return
        loan = None
        if cmd.loan_id:
            loan = session.get(Loan, cmd.loan_id)
        if loan is None:
            loan = _active_loan_for(session, user.id)
        if loan is None:
            send_text(chat_id, "No loan to settle.")
            return
        if not can_lender_settle(loan):
            send_text(chat_id, "Clerk has to SETTLE this one in Band first.")
            return
        _settle(session, loan, chat_id)
        start_task("settle", loan.id)
        return

    if cmd.kind == CommandKind.CANCEL:
        loan = _active_loan_for(session, user.id)
        if loan is None or loan.state not in {"matching", "awaiting_deposit"}:
            send_text(chat_id, "Nothing to cancel.")
            return
        loan.state = "cancelled"
        item = session.get(Item, loan.item_id)
        if item is not None and item.status == "reserved":
            item.status = "listed"
        send_text(chat_id, "Cancelled. Item is listed again.")
        return

    send_text(chat_id, LIVE_REPLY)


def handle_payment_succeeded(session: Session, event: dict) -> None:
    data = event.get("data") or {}
    metadata = data.get("metadata") or {}
    loan_id = metadata.get("loan_id")
    request_id = data.get("id")
    stripe = data.get("stripe") or {}
    pi = stripe.get("payment_intent_id")
    loan = None
    if loan_id:
        loan = session.get(Loan, str(loan_id))
    if loan is None and request_id:
        loan = session.execute(
            select(Loan).where(Loan.linq_payment_request_id == str(request_id))
        ).scalar_one_or_none()
    if loan is None:
        log.warning("payment.succeeded with no loan data=%s", data)
        return
    if not loan.stripe_payment_intent_id and pi:
        loan.stripe_payment_intent_id = str(pi)
    if loan.state == "awaiting_deposit":
        # PRD 6: `walking` without a payment intent is an illegal transition. No PI
        # means no refund is possible later, so hold the loan instead of advancing.
        if not loan.stripe_payment_intent_id:
            log.error("payment.succeeded without payment_intent_id loan=%s", loan.id)
            return
        loan.state = "walking"
        item = session.get(Item, loan.item_id)
        if item is not None:
            item.status = "out"
        if loan.borrower_chat_id:
            send_text(
                loan.borrower_chat_id,
                "Paid. Meet the lender. When you are holding it, reply GOT IT.",
            )
            request_location(loan.borrower_chat_id)
        if loan.lender_chat_id:
            send_text(
                loan.lender_chat_id,
                "Deposit paid. Hand the item over. When they have it, reply GOT IT.",
            )
            request_location(loan.lender_chat_id)
        start_task("onDepositPaid", loan.id)
        # Either side may have said GOT IT before the webhook landed.
        if _try_hand_off(loan):
            for chat in (loan.borrower_chat_id, loan.lender_chat_id):
                if chat:
                    send_text(chat, "Both said GOT IT. Loan is out.")
            start_task("onHandoff", loan.id)


def _try_hand_off(loan: Loan) -> bool:
    """Promote walking -> out once both sides have said GOT IT. Idempotent."""
    if loan.state != "walking":
        return False
    if not (loan.borrower_got_it_at and loan.lender_got_it_at):
        return False
    loan.state = "out"
    loan.return_by_at = _now() + timedelta(hours=2)
    return True


def _settle(session: Session, loan: Loan, chat_id: str) -> None:
    if loan.stripe_refund_id:
        send_text(chat_id, f"Already refunded {loan.stripe_refund_id}.")
        return
    if not loan.stripe_payment_intent_id:
        send_text(chat_id, "No Stripe payment intent on this loan yet. Cannot refund.")
        return
    amount = (
        loan.manual_refund_cents
        if loan.manual_refund_cents is not None
        else refund_cents(loan.deposit_cents, loan.rental_cents, loan.platform_fee_cents)
    )
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
    if loan.sandbox_id:
        from app.superserve_client import kill_sandbox

        kill_sandbox(loan.sandbox_id)
    send_text(
        chat_id,
        f"Returned. Lender {_dollars(loan.rental_cents)}. "
        f"RigShare fee {_dollars(loan.platform_fee_cents)}. "
        f"Refunded {_dollars(amount)}. It can take a few days to show on the card.",
    )
    if loan.borrower_chat_id and loan.borrower_chat_id != chat_id:
        send_text(
            loan.borrower_chat_id,
            f"Returned. Refunded {_dollars(amount)}. It can take a few days to show on the card. You're done.",
        )


def _active_loan_for(session: Session, user_id: str) -> Loan | None:
    return session.execute(
        select(Loan)
        .where(
            or_(Loan.borrower_user_id == user_id, Loan.lender_user_id == user_id),
            Loan.state.in_(ACTIVE_STATES),
        )
        .order_by(Loan.created_at.desc())
    ).scalars().first()


def sku_names() -> list[str]:
    return list(SKUS)
