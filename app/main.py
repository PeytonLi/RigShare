from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db, init_db
from app.linq_webhook import WebhookError, event_id, event_type, parse_event, verify_linq_signature
from app.loans import handle_linq_event
from app.models import Item, Loan, record_event

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(title="RigShare", lifespan=lifespan)


@app.get("/health")
def health() -> dict:
    return {"ok": True, "service": "rigshare"}


@app.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    loans = db.execute(select(Loan).order_by(Loan.created_at.desc())).scalars().all()
    items = db.execute(select(Item).order_by(Item.created_at.desc())).scalars().all()
    return TEMPLATES.TemplateResponse(
        "home.html",
        {"request": request, "loans": loans, "items": items, "settings": get_settings()},
    )


@app.get("/loans/{loan_id}", response_class=HTMLResponse)
def loan_detail(loan_id: str, request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    loan = db.get(Loan, loan_id)
    if loan is None:
        return HTMLResponse("loan not found", status_code=404)
    item = db.get(Item, loan.item_id)
    return TEMPLATES.TemplateResponse(
        "loan.html",
        {"request": request, "loan": loan, "item": item},
    )


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
    try:
        _, created = record_event(db, event_id(event), event_type(event), event)
        if created:
            handle_linq_event(db, event)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"ok": True}
