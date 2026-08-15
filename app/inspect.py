from __future__ import annotations

import logging
import time

from sqlalchemy.orm import Session

from app.agent_api import listed_candidates, pick_item
from app.band_client import create_loan_room, post_room_message
from app.catalog import load_weights
from app.config import get_settings
from app.disputes import dispute_url
from app.models import Item, Loan
from app.superserve_client import inspect_outbound, inspect_return, is_blocked
from app.terac_client import approve_submission, list_submissions, open_dispute

log = logging.getLogger("rigshare")


def ensure_loan_room(session: Session, loan: Loan) -> str | None:
    if loan.band_room_id:
        return loan.band_room_id
    room_id = create_loan_room(loan.id)
    if room_id:
        loan.band_room_id = room_id
        session.flush()
    return room_id


def ensure_sandbox(session: Session, loan: Loan) -> str | None:
    if loan.sandbox_id:
        return loan.sandbox_id
    item = session.get(Item, loan.item_id)
    media_id = item.outbound_media_id if item is not None else None
    sandbox_id = inspect_outbound(loan.id, media_id)
    if sandbox_id:
        loan.sandbox_id = sandbox_id
        session.flush()
    return sandbox_id


def run_quote_and_charge(session: Session, loan_id: str) -> dict:
    loan = session.get(Loan, loan_id)
    if loan is None:
        return {"ok": False, "error": "loan not found"}
    item = session.get(Item, loan.item_id)
    sku = item.sku if item is not None else "item"
    ensure_loan_room(session, loan)
    ensure_sandbox(session, loan)
    candidates = listed_candidates(session, sku) if item is not None else []
    if item is not None and item.status == "listed" and item not in candidates:
        candidates = [item, *candidates]
    if loan.band_room_id:
        lines = [
            f"Borrower needs {sku}. loan_id={loan.id}. Call pick_item.",
            f"catalog_weights={load_weights()}",
        ]
        for cand in candidates:
            lines.append(f"- item_id={cand.id} sku={cand.sku} title={cand.title}")
        post_room_message(
            loan.band_room_id,
            "\n".join(lines),
            mention_agent_id=get_settings().band_matcher_agent_id or None,
            mention_handle="Matcher",
        )
    wait = max(0, int(get_settings().matcher_wait_seconds))
    deadline = time.time() + wait
    while time.time() < deadline:
        session.refresh(loan)
        if loan.matched_at:
            break
        time.sleep(0.25)
    if loan.state == "matching" and not loan.matched_at:
        pick_id = candidates[0].id if candidates else loan.item_id
        pick_item(session, loan.id, pick_id, event_id=f"timeout-{loan.id}", source="timeout")
    return {
        "ok": True,
        "task": "quoteAndCharge",
        "loan_id": loan_id,
        "room": loan.band_room_id,
        "matcher_source": loan.matcher_source,
    }


def run_inspect_return(session: Session, loan_id: str) -> dict:
    loan = session.get(Loan, loan_id)
    if loan is None:
        return {"ok": False, "error": "loan not found"}
    if loan.state not in {"returning", "inspecting", "out", "blocked"}:
        return {"ok": True, "skipped": True, "state": loan.state}

    loan.state = "inspecting"
    ensure_loan_room(session, loan)
    sandbox_id = ensure_sandbox(session, loan)
    metric = inspect_return(sandbox_id, loan.return_media_id)
    if metric is not None:
        loan.compare_metric = metric

    settings = get_settings()
    recommended = "BLOCKED" if is_blocked(metric) else "ALLOW"
    if loan.band_room_id:
        from app.config import get_settings as _gs

        base = _gs().public_base_url.rstrip("/")
        out_url = ""
        item = session.get(Item, loan.item_id)
        if item is not None and item.outbound_media_id:
            out_url = f"{base}/media/{item.outbound_media_id}"
        ret_url = f"{base}/media/{loan.return_media_id}" if loan.return_media_id else ""
        post_room_message(
            loan.band_room_id,
            f"Inspect loan_id={loan.id} compare_metric={metric} recommended={recommended}. "
            f"outbound={out_url} return={ret_url}. Call post_condition_verdict ALLOW or BLOCKED.",
            mention_agent_id=settings.band_condition_agent_id or None,
            mention_handle="Condition",
        )
    return {
        "ok": True,
        "blocked": False,
        "recommended": recommended,
        "metric": metric,
        "loan_id": loan_id,
    }


def run_open_dispute(session: Session, loan_id: str) -> dict:
    loan = session.get(Loan, loan_id)
    if loan is None:
        return {"ok": False, "error": "loan not found"}
    url = dispute_url(loan)
    if not loan.terac_opportunity_id:
        opportunity_id = open_dispute(loan.id, url)
        if opportunity_id:
            loan.terac_opportunity_id = opportunity_id
    if loan.band_room_id:
        post_room_message(
            loan.band_room_id,
            f"Hiring a Terac inspector. Verdict page {url} loan_id={loan.id}",
            mention_agent_id=get_settings().band_clerk_agent_id or None,
            mention_handle="Clerk",
        )
    return {
        "ok": True,
        "task": "openDispute",
        "loan_id": loan_id,
        "opportunity_id": loan.terac_opportunity_id,
        "url": url,
    }


def run_on_terac_submission(session: Session, loan_id: str) -> dict:
    loan = session.get(Loan, loan_id)
    if loan is None:
        return {"ok": False, "error": "loan not found"}
    if not loan.terac_opportunity_id:
        return {"ok": False, "error": "no terac opportunity", "loan_id": loan_id}

    if not loan.terac_submission_id:
        submissions = list_submissions(loan.terac_opportunity_id)
        if not submissions:
            return {"ok": True, "pending": True, "loan_id": loan_id}
        submission_id = str(submissions[0].get("id") or "")
        if submission_id:
            loan.terac_submission_id = submission_id
            approve_submission(submission_id)
            session.flush()

    if loan.band_room_id:
        post_room_message(
            loan.band_room_id,
            f"Terac inspector verdict for loan_id={loan.id}: "
            f"{loan.terac_verdict or 'submitted, no verdict recorded'}. "
            f"submission={loan.terac_submission_id}. Clerk: SETTLE or FORFEIT.",
            mention_agent_id=get_settings().band_clerk_agent_id or None,
            mention_handle="Clerk",
        )
    return {
        "ok": True,
        "task": "onTeracSubmission",
        "loan_id": loan_id,
        "submission_id": loan.terac_submission_id,
        "verdict": loan.terac_verdict,
        "forfeit": loan.forfeited_at is not None,
    }
