from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clerk import Unauthorized, apply_clerk_settle, check_secret
from app.config import get_settings
from app.db import get_db, init_db
from app.disputes import ensure_dispute_token, router as disputes_router
from app.linq_webhook import WebhookError, event_id, event_type, parse_event, verify_linq_signature
from app.loans import handle_linq_event
from app.money import refund_cents
from app.models import Item, Loan, record_event
from app.status import Status, status_all, status_summary
from app.workflows_client import start_loan_tasks

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

STATIC_DIR = Path(__file__).parent / "static"

# Loan state -> pipeline stage. Every loan walks these, and a Render Workflow task
# runs each one. `active` is the stage the most recent loan is on.
PIPELINE = [
    {"name": "Ingest", "who": "Linq webhook · Pioneer"},
    {"name": "Quote & charge", "who": "Agent Pay hold"},
    {"name": "Deposit paid", "who": "walking · GOT IT"},
    {"name": "Handoff", "who": "both said GOT IT"},
    {"name": "Return photo", "who": "inspect sandbox"},
    {"name": "Verdict", "who": "Band · Terac"},
    {"name": "Settle", "who": "Stripe refund"},
]

_STATE_TO_STAGE = {
    "matching": 0,
    "awaiting_deposit": 1,
    "walking": 2,
    "out": 3,
    "returning": 4,
    "inspecting": 4,
    "blocked": 5,
    "settling": 6,
    "closed": 6,
    "cancelled": None,
    "forfeited": None,
}

_VENDOR_LABELS = {
    "money": "Linq → Stripe refund",
    "render": "Render web",
    "stripe": "Stripe",
    "linq": "Linq (iMessage)",
    "band": "Band agents",
    "superserve": "Superserve",
    "terac": "Terac",
    "pioneer": "Pioneer",
}


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(title="RigShare", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.include_router(disputes_router)


def _dashboard_context() -> dict:
    statuses = status_all()
    money = statuses.get("money", Status("money", "skip", ""))
    counts = status_summary(statuses)

    active_index = None
    recent = None
    return {
        "settings": get_settings(),
        "vendors": [
            {"key": s.key, "label": _VENDOR_LABELS.get(s.key, s.key), "status": s.status, "detail": s.detail}
            for s in statuses.values()
        ],
        "money_status": money.status,
        "ok_count": counts["pass"] + counts["warn"],
        "vendor_count": len(statuses),
        "from_number": get_settings().linq_from_number,
        "refund_cents": refund_cents,
    }


@app.get("/health")
def health() -> dict:
    return {"ok": True, "service": "rigshare"}


@app.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    loans = db.execute(select(Loan).order_by(Loan.created_at.desc())).scalars().all()
    items = db.execute(select(Item).order_by(Item.created_at.desc())).scalars().all()

    ctx = _dashboard_context()
    ctx.update({"loans": loans, "items": items})

    for loan in loans:
        loan.refund_cents = refund_cents(
            loan.deposit_cents, loan.rental_cents, loan.platform_fee_cents
        )
        item = db.get(Item, loan.item_id)
        loan.title = item.title or item.sku if item is not None else None
        loan.sku = item.sku if item is not None else None

    # Which pipeline stage is "now"? The most recent non-terminal loan.
    stage_now = None
    for loan in loans:
        idx = _STATE_TO_STAGE.get(loan.state)
        if idx is not None:
            stage_now = idx
            break
    pipeline = []
    for i, step in enumerate(PIPELINE):
        clone = dict(step)
        if stage_now is not None:
            clone["done"] = i < stage_now
            clone["active"] = i == stage_now
        pipeline.append(clone)
    ctx["pipeline"] = pipeline

    return TEMPLATES.TemplateResponse(request, "home.html", ctx)


@app.get("/loans/{loan_id}", response_class=HTMLResponse)
def loan_detail(loan_id: str, request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    loan = db.get(Loan, loan_id)
    if loan is None:
        return HTMLResponse("loan not found", status_code=404)
    item = db.get(Item, loan.item_id)
    ctx = _dashboard_context()
    ctx.update(
        {
            "loan": loan,
            "item": item,
            "refund_cents": refund_cents(
                loan.deposit_cents, loan.rental_cents, loan.platform_fee_cents
            ),
            "dispute_token": ensure_dispute_token(loan) if loan.state == "blocked" else None,
        }
    )
    return TEMPLATES.TemplateResponse(request, "loan.html", ctx)


@app.post("/webhooks/linq")
async def linq_webhook(request: Request, db: Session = Depends(get_db)):
    settings = get_settings()
    body = await request.body()
    if not settings.linq_webhook_secret:
        return JSONResponse({"error": "LINQ_WEBHOOK_SECRET not set"}, status_code=503)
    try:
        verify_linq_signature(settings.linq_webhook_secret, body, request.headers)
    except WebhookError as exc:
        return JSONResponse({"error": str(exc)}, status_code=401)

    event = parse_event(body)
    # handle_linq_event does blocking Linq/Stripe HTTP with a 20s timeout. Running
    # it inline would stall the event loop for every other request; PRD 10 wants
    # this handler back under 2s.
    await run_in_threadpool(_process_linq_event, db, event)
    return {"ok": True}


def _process_linq_event(db: Session, event: dict) -> None:
    try:
        _, created = record_event(db, event_id(event), event_type(event), event)
        if created:
            handle_linq_event(db, event)
            loan_id = None
            data = event.get("data") or {}
            meta = data.get("metadata") or {}
            if meta.get("loan_id"):
                loan_id = str(meta["loan_id"])
            start_loan_tasks(event_type(event), loan_id)
        db.commit()
    except Exception:
        db.rollback()
        raise


@app.post("/internal/clerk-settle")
async def clerk_settle(request: Request, db: Session = Depends(get_db)):
    try:
        check_secret(request.headers.get("x-internal-secret"))
    except Unauthorized:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    body = await request.json()
    loan_id = str(body.get("loan_id") or "")
    event_id_value = str(body.get("event_id") or "")
    if not loan_id or not event_id_value:
        return JSONResponse({"error": "loan_id and event_id required"}, status_code=400)
    try:
        loan = apply_clerk_settle(db, loan_id, event_id_value)
        db.commit()
    except ValueError as exc:
        db.rollback()
        return JSONResponse({"error": str(exc)}, status_code=400)
    from app.workflows_client import start_task

    start_task("settle", loan.id)
    return {"ok": True, "loan_id": loan.id, "refund_id": loan.stripe_refund_id}


@app.get("/media/{media_id}")
def media(media_id: str):
    from fastapi.responses import Response

    from app.linq_client import download_media

    return Response(content=download_media(media_id), media_type="image/jpeg")
