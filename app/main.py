from __future__ import annotations

from contextlib import asynccontextmanager
from hashlib import sha256
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
from app.desks import company_desks
from app.disputes import ensure_dispute_token, router as disputes_router
from app.product import load_state, sku_sort_key
from app.survey import router as survey_router
from app.linq_webhook import WebhookError, event_id, event_type, parse_event, verify_linq_signature
from app.loans import handle_linq_event, recover_photos_from_events
from app.media import media_url
from app.money import refund_cents
from app.models import Item, Loan, record_event
from app.status import Status, status_all, status_summary
from app.workflows_client import start_loan_tasks

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
# Templates never build a /media path by hand -- an unsigned one 401s.
TEMPLATES.env.globals["media_url"] = media_url

STATIC_DIR = Path(__file__).parent / "static"

# Loan state -> pipeline stage. Every loan walks these, and a Render Workflow task
# runs each one. `active` is the stage the most recent loan is on.
PIPELINE = [
    {"name": "Ingest", "who": "Linq webhook · Pioneer", "act": "out"},
    {"name": "Quote & charge", "who": "Agent Pay hold", "act": "out"},
    {"name": "Deposit paid", "who": "walking · GOT IT", "act": "out"},
    {"name": "Handoff", "who": "both said GOT IT", "act": "out"},
    {"name": "Return photo", "who": "inspect sandbox", "act": "back"},
    {"name": "Verdict", "who": "Band · Terac", "act": "back"},
    {"name": "Settle", "who": "Stripe refund", "act": "back"},
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
app.include_router(survey_router)


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


def board_rev(db: Session) -> str:
    """Cheap fingerprint of what the dashboard shows. /live polls this."""
    loans = db.execute(
        select(
            Loan.id,
            Loan.state,
            Loan.updated_at,
            Loan.stripe_payment_intent_id,
            Loan.stripe_refund_id,
            Loan.return_media_id,
            Loan.compare_metric,
            Loan.condition_verdict,
        ).order_by(Loan.created_at.desc())
    ).all()
    items = db.execute(
        select(Item.id, Item.status, Item.outbound_media_id).order_by(Item.created_at.desc())
    ).all()
    payload = [tuple("" if col is None else str(col) for col in row) for row in (*loans, *items)]
    return sha256(repr(payload).encode()).hexdigest()[:16]


@app.get("/health")
def health() -> dict:
    return {"ok": True, "service": "rigshare"}


@app.get("/live")
def live(db: Session = Depends(get_db)) -> dict:
    return {"ok": True, "rev": board_rev(db)}


@app.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    if recover_photos_from_events(db):
        db.commit()
    loans = db.execute(select(Loan).order_by(Loan.created_at.desc())).scalars().all()
    items = db.execute(select(Item).order_by(Item.created_at.desc())).scalars().all()

    ctx = _dashboard_context()
    ctx.update({
        "loans": loans,
        "items": sorted(items, key=lambda item: sku_sort_key(item.sku)),
        "desks": company_desks(db),
        "product": load_state(),
    })

    for loan in loans:
        loan.refund_cents = refund_cents(
            loan.deposit_cents, loan.rental_cents, loan.platform_fee_cents
        )
        item = db.get(Item, loan.item_id)
        loan.title = item.title or item.sku if item is not None else None
        loan.sku = item.sku if item is not None else None
        loan.outbound_media_id = item.outbound_media_id if item is not None else None

    # Which pipeline stage is "now"? The most recent non-terminal loan.
    stage_now = None
    for loan in loans:
        idx = _STATE_TO_STAGE.get(loan.state)
        if idx is not None:
            stage_now = idx
            break
    pipeline = []
    acts: list[dict] = []
    for i, step in enumerate(PIPELINE):
        clone = dict(step)
        clone["num"] = i + 1
        if stage_now is not None:
            clone["done"] = i < stage_now
            clone["active"] = i == stage_now
        pipeline.append(clone)
        if not acts or acts[-1]["act"] != clone["act"]:
            acts.append({"act": clone["act"], "steps": []})
        acts[-1]["steps"].append(clone)
    featured_out = None
    featured_back = None
    for loan in loans:
        if _STATE_TO_STAGE.get(loan.state) is not None:
            featured_out = loan.outbound_media_id
            featured_back = loan.return_media_id
            break
    for act in acts:
        if act["act"] == "out":
            act["photo"] = featured_out
            act["photo_label"] = "outbound"
        else:
            act["photo"] = featured_back
            act["photo_label"] = "returned"
    ctx["pipeline"] = pipeline
    ctx["pipeline_acts"] = acts

    return TEMPLATES.TemplateResponse(request, "home.html", ctx)


@app.get("/loans/{loan_id}", response_class=HTMLResponse)
def loan_detail(loan_id: str, request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    if recover_photos_from_events(db):
        db.commit()
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


@app.post("/internal/apply-votes")
async def apply_votes_endpoint(request: Request, db: Session = Depends(get_db)):
    try:
        check_secret(request.headers.get("x-internal-secret"))
    except Unauthorized:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    from dataclasses import asdict

    from app.desks import record_desk
    from app.product import apply_votes

    state = apply_votes(db)
    record_desk(db, "growth", state.growth_detail)
    record_desk(db, "product", state.product_detail)
    db.commit()
    return {"ok": True, **asdict(state)}


async def _internal_agent(action: str, request: Request, db: Session = Depends(get_db)):
    """Signed agent verbs. Band tools POST here: Matcher picks the item, Condition
    delivers ALLOW/BLOCKED, Clerk hires the inspector or forfeits. Nothing here
    talks to Stripe directly; `clerk-settle` starts the settle workflow.
    """
    try:
        check_secret(request.headers.get("x-internal-secret"))
    except Unauthorized:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    body = await request.json()
    loan_id = str(body.get("loan_id") or "")
    event_id_value = str(body.get("event_id") or "")
    if not loan_id or not event_id_value:
        return JSONResponse({"error": "loan_id and event_id required"}, status_code=400)

    from app.agent_api import (
        AgentApiError,
        apply_clerk_forfeit,
        apply_condition_verdict,
        hire_inspector,
        pick_item,
    )

    try:
        if action == "pick-item":
            item_id = str(body.get("item_id") or "")
            if not item_id:
                return JSONResponse({"error": "item_id required"}, status_code=400)
            loan = pick_item(db, loan_id, item_id, event_id_value)
        elif action == "condition-verdict":
            loan = apply_condition_verdict(
                db, loan_id, str(body.get("verdict") or ""), event_id_value,
                str(body.get("reason") or ""),
            )
        elif action == "hire-inspector":
            loan = hire_inspector(db, loan_id, event_id_value)
        elif action == "clerk-forfeit":
            loan = apply_clerk_forfeit(db, loan_id, event_id_value)
        else:
            return JSONResponse({"error": "unknown action"}, status_code=404)
        db.commit()
    except AgentApiError as exc:
        db.rollback()
        return JSONResponse({"error": str(exc)}, status_code=exc.status)
    return {"ok": True, "loan_id": loan.id, "state": loan.state}


@app.post("/internal/pick-item")
async def internal_pick_item(request: Request, db: Session = Depends(get_db)):
    return await _internal_agent("pick-item", request, db)


@app.post("/internal/condition-verdict")
async def internal_condition_verdict(request: Request, db: Session = Depends(get_db)):
    return await _internal_agent("condition-verdict", request, db)


@app.post("/internal/hire-inspector")
async def internal_hire_inspector(request: Request, db: Session = Depends(get_db)):
    return await _internal_agent("hire-inspector", request, db)


@app.post("/internal/clerk-forfeit")
async def internal_clerk_forfeit(request: Request, db: Session = Depends(get_db)):
    return await _internal_agent("clerk-forfeit", request, db)


@app.get("/media/{media_id}")
def media(media_id: str, s: str | None = None):
    from fastapi.responses import Response

    from app.linq_client import fetch_media
    from app.media import media_signature_ok

    if not media_signature_ok(media_id, s):
        return JSONResponse({"error": "bad or missing signature"}, status_code=401)
    try:
        body, content_type = fetch_media(media_id)
    except Exception:
        return JSONResponse({"error": "media fetch failed"}, status_code=502)
    if not content_type.startswith("image/"):
        content_type = "image/jpeg"
    return Response(content=body, media_type=content_type)
