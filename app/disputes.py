from __future__ import annotations

import hmac
import secrets
from pathlib import Path
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.media import media_url
from app.models import Item, Loan, utcnow

router = APIRouter()

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
# The Terac inspector has no login, so their photos come in on a signed URL.
TEMPLATES.env.globals["media_url"] = media_url

VERDICTS = {"fine", "damaged", "different"}

# ponytail: one flat damage cut for every SKU. Ceiling: the refund can never go
# below 0 and never above the clean refund. Per-SKU or inspector-entered severity
# if this ever bills someone real money.
DAMAGE_CUT_CENTS = 1000


def ensure_dispute_token(loan: Loan) -> str:
    if not loan.dispute_token:
        loan.dispute_token = secrets.token_urlsafe(16)
    return loan.dispute_token


def dispute_url(loan: Loan) -> str:
    base = get_settings().public_base_url.rstrip("/")
    return f"{base}/disputes/{loan.id}?t={ensure_dispute_token(loan)}"


def token_ok(loan: Loan, provided: str | None) -> bool:
    # No token minted yet means nobody may open the page: compare_digest("", "")
    # is True, so the emptiness check has to come first.
    if not loan.dispute_token:
        return False
    return hmac.compare_digest(loan.dispute_token, provided or "")


def can_settle_after_dispute(loan: Loan) -> bool:
    """PRD 7.5 delete test: a BLOCKED loan stays stuck until a human decided.

    A Terac submission/verdict, or a lender override (`manual_refund_cents` set by
    hand), unsticks it. `different` sets forfeited_at, which is never settle-able.
    """
    if loan.forfeited_at is not None:
        return False
    if loan.state != "blocked":
        return True
    return bool(
        loan.terac_submission_id
        or loan.terac_verdict
        or loan.manual_refund_cents is not None
    )


def apply_forfeit(session: Session, loan: Loan) -> Loan:
    if loan.stripe_refund_id:
        raise ValueError("already refunded")
    apply_verdict(loan, "different")
    item = session.get(Item, loan.item_id)
    if item is not None:
        item.status = "retired"
    if loan.sandbox_id:
        from app.superserve_client import kill_sandbox

        kill_sandbox(loan.sandbox_id)
    return loan


def apply_verdict(loan: Loan, verdict: str) -> None:
    """Write the verdict only. Stripe is Clerk's / the settle workflow's job."""
    loan.terac_verdict = verdict
    if verdict == "fine":
        loan.manual_refund_cents = None
        loan.state = "inspecting"
    elif verdict == "damaged":
        clean = loan.deposit_cents - loan.rental_cents - loan.platform_fee_cents
        loan.manual_refund_cents = max(0, clean - DAMAGE_CUT_CENTS)
        loan.state = "inspecting"
    else:
        loan.forfeited_at = utcnow()
        loan.state = "forfeited"


@router.get("/disputes/{loan_id}", response_class=HTMLResponse)
def dispute_page(
    loan_id: str, request: Request, t: str | None = None, db: Session = Depends(get_db)
) -> HTMLResponse:
    loan = db.get(Loan, loan_id)
    if loan is None:
        return HTMLResponse("loan not found", status_code=404)
    if not token_ok(loan, t):
        return HTMLResponse("bad or missing token", status_code=401)
    item = db.get(Item, loan.item_id)
    from app.money import refund_cents

    return TEMPLATES.TemplateResponse(
        request,
        "dispute.html",
        {
            "loan": loan,
            "item": item,
            "token": t,
            "refund_cents": refund_cents(
                loan.deposit_cents, loan.rental_cents, loan.platform_fee_cents
            ),
        },
    )


@router.post("/disputes/{loan_id}", response_class=HTMLResponse)
async def dispute_verdict(
    loan_id: str, request: Request, t: str | None = None, db: Session = Depends(get_db)
) -> HTMLResponse:
    loan = db.get(Loan, loan_id)
    if loan is None:
        return HTMLResponse("loan not found", status_code=404)
    if not token_ok(loan, t):
        return HTMLResponse("bad or missing token", status_code=401)

    # python-multipart is not installed, and a three-button HTML form is urlencoded.
    form = parse_qs((await request.body()).decode())
    verdict = (form.get("verdict") or [""])[0]
    if verdict not in VERDICTS:
        return HTMLResponse("verdict must be fine, damaged or different", status_code=400)

    apply_verdict(loan, verdict)
    db.commit()
    # The inspector tapping a button is the only signal a submission exists; nothing
    # polls Terac on a timer. onTeracSubmission approves it so the human gets paid.
    from app.workflows_client import start_task

    start_task("onTeracSubmission", loan.id)
    if verdict == "different":
        start_task("forfeit", loan.id)
    return HTMLResponse(
        "<!doctype html><meta charset=utf-8><title>Thanks</title>"
        "<p style='font-family:ui-sans-serif,system-ui,sans-serif;margin:2rem'>"
        "Thanks. Recorded. You can close this tab.</p>"
    )
