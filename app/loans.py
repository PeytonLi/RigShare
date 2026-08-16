from __future__ import annotations

import json
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
from app.models import Item, Loan, ProcessedEvent, User, get_or_create_user
from app.replies import render
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


def _say(chat_id: str, key: str, *, loan: Loan | None = None, **slots: object) -> None:
    """Send one reply. The registry template is the fallback; Pioneer rewrites it.

    Copy lives in app/replies.py, never inline here -- see that module for why.
    """
    fallback = render(key, **slots)
    text, source = compose_reply(key, fallback, slots)
    send_text(chat_id, text)
    if loan is not None:
        loan.copy_source = source


def _photo_id(user, media: list[str]) -> str | None:
    return media[0] if media else user.last_media_id


def _attach_loose_photo(session: Session, user, media_id: str, chat_id: str | None = None) -> bool:
    """A photo often arrives as its own iMessage, then LEND / RETURNING follows.

    Scoped to the chat it actually arrived in when one is known; a photo from a
    different conversation must never fill a blank in another loan's photos.
    """
    item = session.execute(
        select(Item)
        .where(
            Item.lender_user_id == user.id,
            Item.outbound_media_id.is_(None),
            Item.status.in_(("pending", "listed", "reserved", "out")),
            Item.lender_chat_id == chat_id if chat_id else True,
        )
        .order_by(Item.created_at.desc())
    ).scalars().first()
    if item is not None:
        item.outbound_media_id = media_id
        return True
    loan = session.execute(
        select(Loan)
        .where(
            Loan.borrower_user_id == user.id,
            Loan.return_media_id.is_(None),
            Loan.state.in_(
                ("out", "returning", "inspecting", "settling", "blocked", "closed")
            ),
            Loan.borrower_chat_id == chat_id if chat_id else True,
        )
        .order_by(Loan.created_at.desc())
    ).scalars().first()
    if loan is not None:
        loan.return_media_id = media_id
        return True
    return False


def _media_timeline(
    session: Session,
) -> list[tuple[datetime, str | None, str | None, str]]:
    """[(arrived_at, chat_id, phone, media_id)] for every media-bearing message."""
    timeline: list[tuple[datetime, str | None, str | None, str]] = []
    rows = session.execute(
        select(ProcessedEvent)
        .where(ProcessedEvent.event_type == "message.received")
        .order_by(ProcessedEvent.created_at.asc())
    ).scalars().all()
    for row in rows:
        try:
            payload = json.loads(row.payload_json)
        except json.JSONDecodeError:
            continue
        chat = inbound_chat_id(payload)
        phone = inbound_from_phone(payload)
        for media_id in inbound_media_ids(payload):
            timeline.append((row.created_at, chat, phone, media_id))
    return timeline


def _nearest_media(
    timeline: list[tuple[datetime, str | None, str | None, str]],
    *,
    chat: str | None = None,
    phone: str | None = None,
    anchor: datetime,
) -> str | None:
    """The media id closest in time to `anchor` that matches the filters."""
    best: str | None = None
    best_delta: float | None = None
    for arrived, hit_chat, hit_phone, media_id in timeline:
        if chat is not None and hit_chat != chat:
            continue
        if phone is not None and hit_phone != phone:
            continue
        delta = abs((arrived - anchor).total_seconds())
        if best_delta is None or delta < best_delta:
            best_delta = delta
            best = media_id
    return best


def recover_photos_from_events(session: Session) -> bool:
    """Backfill outbound/return ids from stored Linq webhooks (split photo texts).

    Matches by chat + time, not "the most recent photo that phone ever sent".
    The old phone-wide match stamped the same latest photo onto every listing and
    every return, which is why the dashboard showed identical outbound/return
    images that belonged to no specific loan. A chat-correlated match also
    overwrites a wrong id, so already-polluted rows heal on the next page load.
    """
    timeline = _media_timeline(session)
    if not timeline:
        return False
    items = session.execute(select(Item)).scalars().all()
    loans = session.execute(select(Loan)).scalars().all()
    if not items and not loans:
        return False
    users = {u.id: u for u in session.execute(select(User)).scalars().all()}
    changed = False
    for item in items:
        matched = None
        if item.lender_chat_id:
            matched = _nearest_media(timeline, chat=item.lender_chat_id, anchor=item.created_at)
        if matched is None:
            lender = users.get(item.lender_user_id)
            if lender is not None and lender.phone:
                matched = _nearest_media(timeline, phone=lender.phone, anchor=item.created_at)
        if matched and matched != item.outbound_media_id:
            item.outbound_media_id = matched
            changed = True
    for loan in loans:
        anchor = loan.updated_at or loan.created_at
        matched = None
        if loan.borrower_chat_id:
            matched = _nearest_media(timeline, chat=loan.borrower_chat_id, anchor=anchor)
        if matched is None:
            borrower = users.get(loan.borrower_user_id)
            if borrower is not None and borrower.phone:
                matched = _nearest_media(timeline, phone=borrower.phone, anchor=anchor)
        if matched and matched != loan.return_media_id:
            loan.return_media_id = matched
            changed = True
    return changed


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
    _say(other, "location_ping", maps_url=f"https://maps.google.com/?q={lat},{lng}")


def handle_inbound(session: Session, event: dict) -> None:
    text = inbound_text(event) or ""
    chat_id = inbound_chat_id(event)
    phone = inbound_from_phone(event)
    if not chat_id or not phone:
        log.warning("inbound missing chat or phone event=%s", event_id(event))
        return

    user = get_or_create_user(session, phone)
    media = inbound_media_ids(event)
    if media:
        user.last_media_id = media[0]
    if not text.strip() and media:
        _attach_loose_photo(session, user, media[0], chat_id)
        return
    cmd = enrich_command(text, parse_command(text))
    if cmd.kind == "UNSAFE":
        _say(chat_id, "unsafe")
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
            _say(chat_id, "lend_no_sku")
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
            outbound_media_id=_photo_id(user, media),
            lender_chat_id=chat_id,
        )
        session.add(item)
        session.flush()
        _say(
            chat_id,
            "lend_confirm",
            title=item.title,
            deposit=_dollars(money.deposit_cents),
            rental=_dollars(money.rental_cents),
            fee=_dollars(money.platform_fee_cents),
        )
        return

    if cmd.kind == CommandKind.YES:
        item = session.execute(
            select(Item)
            .where(Item.lender_user_id == user.id, Item.status == "pending")
            .order_by(Item.created_at.desc())
        ).scalars().first()
        if item is None:
            _say(chat_id, "yes_nothing_pending")
            return
        item.status = "listed"
        item.lender_chat_id = chat_id
        _say(
            chat_id,
            "yes_listed",
            title=item.title,
            deposit=_dollars(item.deposit_cents),
            rental=_dollars(item.rental_cents),
        )
        return

    if cmd.kind == CommandKind.NEED:
        sku = cmd.sku
        if sku is None:
            _say(chat_id, "need_no_sku")
            return
        candidates = listed_candidates(session, sku)
        item = candidates[0] if candidates else None
        if item is None:
            _say(chat_id, "need_none_listed", sku=sku.replace("_", " "))
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
        _say(chat_id, "need_matching", loan=loan, sku=label)
        start_task("quoteAndCharge", loan.id)
        return

    if cmd.kind == CommandKind.PAID:
        loan = _active_loan_for(session, user.id)
        if loan is None or loan.state != "awaiting_deposit":
            _say(chat_id, "paid_none_waiting")
            return
        if not _confirm_payment_from_linq(session, loan):
            _say(chat_id, "paid_not_seen")
        return

    if cmd.kind == CommandKind.GOT_IT:
        loan = _active_loan_for(session, user.id)
        if loan is None:
            _say(chat_id, "got_it_no_loan")
            return
        if user.id == loan.borrower_user_id:
            loan.borrower_got_it_at = _now()
            loan.borrower_chat_id = chat_id
        if user.id == loan.lender_user_id:
            loan.lender_got_it_at = _now()
            loan.lender_chat_id = chat_id
        if _try_hand_off(loan):
            _say(chat_id, "handoff_holder")
            other = loan.lender_chat_id if user.id == loan.borrower_user_id else loan.borrower_chat_id
            if other and other != chat_id:
                _say(other, "handoff_other")
            _send_status_link(loan)
            start_task("onHandoff", loan.id)
        elif loan.state == "awaiting_deposit":
            _say(chat_id, "got_it_awaiting_deposit")
        else:
            _say(chat_id, "got_it_waiting_other")
        return

    if cmd.kind == CommandKind.RETURNING:
        loan = _active_loan_for(session, user.id)
        if loan is None:
            _say(chat_id, "returning_no_loan")
            return
        if loan.state not in {"out", "returning"}:
            _say(chat_id, "returning_not_out")
            return
        loan.state = "returning"
        photo = _photo_id(user, media)
        if photo:
            loan.return_media_id = photo
        _say(chat_id, "returning", loan=loan)
        start_task("inspectReturn", loan.id)
        return

    if cmd.kind == CommandKind.SETTLE:
        if not is_lender:
            _say(chat_id, "settle_not_lender")
            return
        loan = None
        if cmd.loan_id:
            loan = session.get(Loan, cmd.loan_id)
        if loan is None:
            loan = _active_loan_for(session, user.id)
        if loan is None:
            _say(chat_id, "settle_no_loan")
            return
        if loan.stripe_refund_id:
            _say(chat_id, "settle_already_refunded", refund_id=loan.stripe_refund_id)
            return
        _say(chat_id, "settle_clerk_required")
        return

    if cmd.kind == CommandKind.CANCEL:
        loan = _active_loan_for(session, user.id)
        if loan is None or loan.state not in {"matching", "awaiting_deposit"}:
            _say(chat_id, "cancel_nothing")
            return
        loan.state = "cancelled"
        item = session.get(Item, loan.item_id)
        if item is not None and item.status == "reserved":
            item.status = "listed"
        _say(chat_id, "cancel_done")
        return

    if media and _attach_loose_photo(session, user, media[0], chat_id):
        return
    loan = _active_loan_for(session, user.id)
    if loan is not None and loan.state == "awaiting_deposit":
        if _confirm_payment_from_linq(session, loan):
            return
        _say(chat_id, "paid_prompt")
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
        _say(loan.borrower_chat_id, "deposit_paid_borrower")
        _safe_request_location(loan.borrower_chat_id)
    if loan.lender_chat_id:
        _say(loan.lender_chat_id, "deposit_paid_lender")
        _safe_request_location(loan.lender_chat_id)
    start_task("onDepositPaid", loan.id)
    if _try_hand_off(loan):
        for chat in (loan.borrower_chat_id, loan.lender_chat_id):
            if chat:
                _say(chat, "handoff_other")
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
            _say(loan.borrower_chat_id, "payment_missing_stripe_id")


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
        _say(chat_id, "settle_already_refunded", refund_id=loan.stripe_refund_id)
        return
    if not loan.stripe_payment_intent_id:
        _say(chat_id, "settle_no_payment_intent")
        return
    try:
        amount = settle_loan(session, loan)
    except ValueError as exc:
        _say(chat_id, "settle_blocked", reason=str(exc))
        return
    if loan.sandbox_id:
        from app.superserve_client import kill_sandbox

        kill_sandbox(loan.sandbox_id)
    _say(
        chat_id,
        "settle_receipt_lender",
        rental=_dollars(loan.rental_cents),
        fee=_dollars(loan.platform_fee_cents),
        refund=_dollars(amount),
    )
    if loan.borrower_chat_id and loan.borrower_chat_id != chat_id:
        _say(loan.borrower_chat_id, "settle_receipt_borrower", refund=_dollars(amount))
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
