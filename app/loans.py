from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.agent_api import listed_candidates, persist_entities
from app.clerk import settle_loan
from app.commands import CommandKind, parse_command
from app.config import get_settings
from app.counsel import review_listing
from app.desks import record_desk
from app.ingest import enrich_command
from app.linq_client import (
    create_payment_request,
    get_location,
    get_payment_request,
    request_location,
    send_link,
    send_text,
)
from app.product import borrower_quote, live_reply
from app.pioneer_client import compose_reply
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
from app.skus import SKUS, resolve_sku

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


def _say(chat_id: str, fallback: str, template_key: str, slots: dict | None = None, loan: Loan | None = None) -> None:
    text, source = compose_reply(template_key, fallback, slots)
    send_text(chat_id, text)
    if loan is not None:
        loan.copy_source = source


def handle_linq_event(session: Session, event: dict) -> None:
    kind = event_type(event)
    if kind == "message.received":
        handle_inbound(session, event)
        return
    if kind in {"payment.succeeded", "payment.authorized"}:
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
        decision = review_listing(
            text,
            sku,
            demo=settings.demo_mode and cmd.deposit_cents is None,
            deposit_cents=cmd.deposit_cents,
            rental_cents=cmd.rental_cents,
        )
        if not decision.allowed:
            send_text(chat_id, decision.message)
            record_desk(session, "counsel", decision.message)
            return
        if sku is None:
            send_text(chat_id, "What are you lending? Reply LEND HDMI, LEND USB-C, or LEND LIGHTNING. Orange tape on it.")
            return
        money = decision.money
        assert money is not None
        item = Item(
            id=uuid.uuid4().hex,
            sku=sku,
            title=sku.replace("_", " "),
            lender_user_id=user.id,
            # PRD 5.1: nothing is borrowable until the lender confirms the money.
            status="pending",
            deposit_cents=money.deposit_cents,
            rental_cents=money.rental_cents,
            platform_fee_cents=money.platform_fee_cents,
            outbound_media_id=media[0] if media else None,
            lender_chat_id=chat_id,
        )
        session.add(item)
        session.flush()
        _say(
            chat_id,
            f"Got it. {item.title}, orange tape. {_dollars(money.deposit_cents)} hold. "
            f"You get {_dollars(money.rental_cents)} when it comes back. "
            f"Borrower also pays a {_dollars(money.platform_fee_cents)} RigShare fee (not taken from you). "
            "Reply YES to list it. Mark the item so we can tell it apart.",
            "lend_confirm",
            {
                "title": item.title,
                "deposit": _dollars(money.deposit_cents),
                "rental": _dollars(money.rental_cents),
                "fee": _dollars(money.platform_fee_cents),
            },
        )
        return

    if cmd.kind == CommandKind.YES:
        item = session.execute(
            select(Item)
            .where(Item.lender_user_id == user.id, Item.status == "pending")
            .order_by(Item.created_at.desc())
        ).scalars().first()
        if item is None:
            send_text(chat_id, "Nothing waiting to be listed. Text LEND HDMI / USB-C / LIGHTNING with a photo.")
            return
        item.status = "listed"
        item.lender_chat_id = chat_id
        send_text(
            chat_id,
            f"Listed {item.title}. {_dollars(item.deposit_cents)} hold on the borrower. "
            f"You get {_dollars(item.rental_cents)} when it comes back.",
        )
        return

    if cmd.kind == CommandKind.NEED:
        sku = cmd.sku
        if sku is None:
            send_text(chat_id, "What do you need? NEED HDMI, NEED USB-C, or NEED LIGHTNING.")
            return
        candidates = listed_candidates(session, sku)
        item = candidates[0] if candidates else None
        if item is None:
            send_text(chat_id, f"Nothing listed for {sku.replace('_', ' ')} yet. Ask someone to LEND.")
            return
        loan = Loan(
            id=uuid.uuid4().hex,
            item_id=item.id,
            borrower_user_id=user.id,
            lender_user_id=item.lender_user_id,
            state="matching",
            borrower_chat_id=chat_id,
            lender_chat_id=item.lender_chat_id,
            deposit_cents=item.deposit_cents,
            rental_cents=item.rental_cents,
            platform_fee_cents=item.platform_fee_cents,
        )
        session.add(loan)
        persist_entities(loan, cmd.entities)
        session.flush()
        label = sku.replace("_", " ")
        _say(
            chat_id,
            f"Looking for a {label} nearby…",
            "need_matching",
            {"sku": label, "loan_id": loan.id},
            loan,
        )
        start_task("quoteAndCharge", loan.id)
        return

    if cmd.kind == CommandKind.PAID:
        loan = _active_loan_for(session, user.id)
        if loan is None or loan.state != "awaiting_deposit":
            send_text(chat_id, "No deposit waiting. If you already have the item, reply GOT IT.")
            return
        if not _confirm_payment_from_linq(session, loan):
            send_text(
                chat_id,
                "I don't see the payment yet. Wait 10 seconds and reply PAID again.",
            )
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
            _send_status_link(loan)
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
        _say(
            chat_id,
            "Return photo in. Condition is looking at the orange tape.",
            "returning",
            {"loan_id": loan.id},
            loan,
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
        if loan.stripe_refund_id:
            send_text(chat_id, f"Already refunded {loan.stripe_refund_id}.")
            return
        send_text(chat_id, "Clerk has to SETTLE this one in Band first.")
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

    loan = _active_loan_for(session, user.id)
    if loan is not None and loan.state == "awaiting_deposit":
        if _confirm_payment_from_linq(session, loan):
            return
        send_text(chat_id, "If you already paid, reply PAID. If not, use the pay link I sent.")
        return
    send_text(chat_id, live_reply())


_PAID_STATUSES = {
    "succeeded",
    "paid",
    "authorized",
    "complete",
    "completed",
    "captured",
}


def _payment_fields(event: dict) -> tuple[str | None, str | None, str | None]:
    data = event.get("data") or {}
    nested = data.get("payment_request") if isinstance(data.get("payment_request"), dict) else {}
    metadata = data.get("metadata") or nested.get("metadata") or {}
    loan_id = metadata.get("loan_id")
    request_id = data.get("id") or data.get("payment_request_id") or nested.get("id")
    stripe = data.get("stripe") or nested.get("stripe") or {}
    pi = stripe.get("payment_intent_id") or data.get("payment_intent_id")
    return (
        str(loan_id) if loan_id else None,
        str(request_id) if request_id else None,
        str(pi) if pi else None,
    )


def _safe_request_location(chat_id: str) -> None:
    try:
        request_location(chat_id)
    except Exception:
        log.exception("location request failed chat=%s", chat_id)


def _mark_deposit_paid(session: Session, loan: Loan, payment_intent_id: str | None) -> bool:
    if payment_intent_id and not loan.stripe_payment_intent_id:
        loan.stripe_payment_intent_id = payment_intent_id
    if loan.state != "awaiting_deposit":
        return bool(loan.stripe_payment_intent_id)
    if not loan.stripe_payment_intent_id:
        log.error("payment without payment_intent_id loan=%s", loan.id)
        return False
    loan.state = "walking"
    item = session.get(Item, loan.item_id)
    if item is not None:
        item.status = "out"
    if loan.borrower_chat_id:
        send_text(
            loan.borrower_chat_id,
            "Paid. Meet the lender. When you are holding it, reply GOT IT.",
        )
        _safe_request_location(loan.borrower_chat_id)
    if loan.lender_chat_id:
        send_text(
            loan.lender_chat_id,
            "Deposit paid. Hand the item over. When they have it, reply GOT IT.",
        )
        _safe_request_location(loan.lender_chat_id)
    start_task("onDepositPaid", loan.id)
    if _try_hand_off(loan):
        for chat in (loan.borrower_chat_id, loan.lender_chat_id):
            if chat:
                send_text(chat, "Both said GOT IT. Loan is out.")
        start_task("onHandoff", loan.id)
    return True


def _confirm_payment_from_linq(session: Session, loan: Loan) -> bool:
    if not loan.linq_payment_request_id:
        return False
    record = get_payment_request(loan.linq_payment_request_id)
    if not record:
        return False
    status = str(record.get("status") or "").lower()
    if status not in _PAID_STATUSES:
        return False
    stripe = record.get("stripe") or {}
    pi = stripe.get("payment_intent_id") or record.get("payment_intent_id")
    return _mark_deposit_paid(session, loan, str(pi) if pi else None)


def handle_payment_succeeded(session: Session, event: dict) -> None:
    loan_id, request_id, pi = _payment_fields(event)
    loan = None
    if loan_id:
        loan = session.get(Loan, loan_id)
    if loan is None and request_id:
        loan = session.execute(
            select(Loan).where(Loan.linq_payment_request_id == request_id)
        ).scalar_one_or_none()
    if loan is None:
        log.warning("payment event with no loan data=%s", event.get("data"))
        return
    if not pi and (request_id or loan.linq_payment_request_id):
        record = get_payment_request(request_id or loan.linq_payment_request_id or "")
        if record:
            stripe = record.get("stripe") or {}
            pi = stripe.get("payment_intent_id") or record.get("payment_intent_id")
            pi = str(pi) if pi else None
    if not _mark_deposit_paid(session, loan, pi):
        if loan.borrower_chat_id:
            send_text(
                loan.borrower_chat_id,
                "Payment came in but I still need the Stripe id. Reply PAID in a few seconds.",
            )


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
    try:
        amount = settle_loan(session, loan)
    except ValueError as exc:
        send_text(chat_id, f"Cannot settle yet: {exc}")
        return
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
    _send_status_link(loan)


def _send_status_link(loan: Loan) -> None:
    """PRD 7.1: the receipt page, after a state a human cares about.

    Never on the first message of a chat -- Linq drops links that open a thread.
    """
    url = f"{get_settings().public_base_url.rstrip('/')}/loans/{loan.id}"
    for chat in (loan.borrower_chat_id, loan.lender_chat_id):
        if chat:
            send_link(chat, url)


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
