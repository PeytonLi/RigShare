from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.band_client import create_loan_room, post_room_message
from app.config import get_settings
from app.linq_client import send_text
from app.models import Item, Loan
from app.superserve_client import (
    AE_BLOCK_THRESHOLD,
    compare_return_photo,
    ensure_outbound_sandbox,
)
from app.terac_client import create_activity_opportunity

log = logging.getLogger("rigshare")


def ensure_loan_room(session: Session, loan: Loan) -> str | None:
    if loan.band_room_id:
        return loan.band_room_id
    room_id = create_loan_room(loan.id)
    if room_id:
        loan.band_room_id = room_id
        session.flush()
    return room_id


def ensure_sandbox(session: Session, loan: Loan, jpeg: bytes = b"") -> str | None:
    if loan.sandbox_id:
        return loan.sandbox_id
    sandbox_id = ensure_outbound_sandbox(loan.id, jpeg)
    if sandbox_id:
        loan.sandbox_id = sandbox_id
        session.flush()
    return sandbox_id


def run_quote_and_charge(session: Session, loan_id: str) -> dict:
    loan = session.get(Loan, loan_id)
    if loan is None:
        return {"ok": False, "error": "loan not found"}
    item = session.get(Item, loan.item_id)
    ensure_loan_room(session, loan)
    jpeg = b""
    ensure_sandbox(session, loan, jpeg)
    room_id = loan.band_room_id
    if room_id:
        sku = item.sku if item is not None else "item"
        post_room_message(
            room_id,
            f"Borrower needs {sku}. loan_id={loan.id}. Pick the listed item.",
            mention_agent_id=get_settings().band_matcher_agent_id or None,
            mention_handle="Matcher",
        )
    return {"ok": True, "task": "quoteAndCharge", "loan_id": loan_id, "room": loan.band_room_id}


def run_inspect_return(session: Session, loan_id: str) -> dict:
    loan = session.get(Loan, loan_id)
    if loan is None:
        return {"ok": False, "error": "loan not found"}
    if loan.state not in {"returning", "inspecting", "out", "blocked"}:
        return {"ok": True, "skipped": True, "state": loan.state}

    loan.state = "inspecting"
    ensure_loan_room(session, loan)
    sandbox_id = ensure_sandbox(session, loan, b"")
    metric = None
    if sandbox_id:
        metric = compare_return_photo(sandbox_id, b"")
        if metric is not None:
            loan.compare_metric = metric

    settings = get_settings()
    blocked = metric is not None and metric > AE_BLOCK_THRESHOLD
    if blocked:
        loan.state = "blocked"
        if loan.borrower_chat_id:
            send_text(
                loan.borrower_chat_id,
                "Return doesn't match the outbound photo (missing orange tape). "
                "Deposit stays held. Lender is looking at it.",
            )
        if loan.band_room_id:
            post_room_message(
                loan.band_room_id,
                f"BLOCKED loan_id={loan.id} compare_metric={metric}. Tape missing or wrong item?",
                mention_agent_id=settings.band_condition_agent_id or None,
                mention_handle="Condition",
            )
        run_open_dispute(session, loan.id)
        return {"ok": True, "blocked": True, "metric": metric, "loan_id": loan_id}

    loan.state = "returning"
    if loan.lender_chat_id:
        send_text(
            loan.lender_chat_id,
            f"Return photo in. Metric {metric if metric is not None else 'n/a'}. "
            f"Reply SETTLE {loan.id} if the orange tape matches.",
        )
    if loan.band_room_id:
        post_room_message(
            loan.band_room_id,
            f"ALLOW recommended loan_id={loan.id} compare_metric={metric}. Confirm then Clerk SETTLE.",
            mention_agent_id=settings.band_condition_agent_id or None,
            mention_handle="Condition",
        )
    return {"ok": True, "blocked": False, "metric": metric, "loan_id": loan_id}


def run_open_dispute(session: Session, loan_id: str) -> dict:
    loan = session.get(Loan, loan_id)
    if loan is None:
        return {"ok": False, "error": "loan not found"}
    if not loan.dispute_token:
        import uuid

        loan.dispute_token = uuid.uuid4().hex
    settings = get_settings()
    url = f"{settings.public_base_url.rstrip('/')}/disputes/{loan.id}?t={loan.dispute_token}"
    if not loan.terac_opportunity_id:
        opportunity_id = create_activity_opportunity(
            title=f"RigShare dispute {loan.id[:8]}",
            task_url=url,
            description="Compare outbound vs return. Tap Same item fine / damaged / Different item.",
        )
        if opportunity_id:
            loan.terac_opportunity_id = opportunity_id
    if loan.band_room_id:
        post_room_message(
            loan.band_room_id,
            f"Hiring a Terac inspector. Verdict page {url} loan_id={loan.id}",
            mention_agent_id=settings.band_clerk_agent_id or None,
            mention_handle="Clerk",
        )
    return {
        "ok": True,
        "task": "openDispute",
        "loan_id": loan_id,
        "opportunity_id": loan.terac_opportunity_id,
        "url": url,
    }
