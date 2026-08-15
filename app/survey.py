"""Hosted Terac activity: catalog + pitch + fee fairness. General population."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import SurveyResponse
from app.product import CATALOG_OPTIONS, NONE_LABEL, PITCH_A, PITCH_B, tally

router = APIRouter()
TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

TERAC_CALLBACK = "https://terac.com/api/external/callback"
CATALOG_LABELS = [label for _, label in CATALOG_OPTIONS] + [NONE_LABEL]
PITCH_CHOICES = (("a", PITCH_A), ("b", PITCH_B))
FEE_CHOICES = (
    ("fair", "Fair"),
    ("greedy", "Greedy"),
    ("confusing", "Confusing"),
)


def _terac_ids(request: Request) -> dict[str, str]:
    q = request.query_params
    submission = q.get("teracSubmissionId") or q.get("submissionId") or ""
    task = q.get("taskId") or ""
    return {"submission_id": submission, "task_id": task}


def _callback_url(submission_id: str, task_id: str) -> str | None:
    if not submission_id:
        return None
    params = {
        "submissionId": submission_id,
        "teracSubmissionId": submission_id,
        "result": "completed",
    }
    if task_id:
        params["taskId"] = task_id
    return f"{TERAC_CALLBACK}?{urlencode(params)}"


def _parse_body(raw: bytes) -> dict[str, list[str]]:
    from urllib.parse import parse_qs

    return parse_qs(raw.decode())


@router.get("/survey", response_class=HTMLResponse)
def survey_page(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    ids = _terac_ids(request)
    return TEMPLATES.TemplateResponse(
        request,
        "survey.html",
        {
            "catalog_labels": CATALOG_LABELS,
            "pitches": PITCH_CHOICES,
            "fees": FEE_CHOICES,
            "submission_id": ids["submission_id"],
            "task_id": ids["task_id"],
            "error": None,
            "tally": tally(db),
        },
    )


@router.post("/survey")
async def survey_submit(request: Request, db: Session = Depends(get_db)):
    ids = _terac_ids(request)
    form = _parse_body(await request.body())
    submission_id = (form.get("submission_id") or [ids["submission_id"]])[0]
    task_id = (form.get("task_id") or [ids["task_id"]])[0]
    catalog = [value for value in form.get("catalog", []) if value in CATALOG_LABELS]
    if NONE_LABEL in catalog:
        catalog = [NONE_LABEL]
    pitch = (form.get("pitch") or [""])[0]
    fee_tone = (form.get("fee") or [""])[0]
    if not catalog or pitch not in {"a", "b"} or fee_tone not in {"fair", "greedy", "confusing"}:
        return TEMPLATES.TemplateResponse(
            request,
            "survey.html",
            {
                "catalog_labels": CATALOG_LABELS,
                "pitches": PITCH_CHOICES,
                "fees": FEE_CHOICES,
                "submission_id": submission_id,
                "task_id": task_id,
                "error": "Pick at least one item, a pitch, and whether the fee feels fair.",
                "tally": tally(db),
            },
            status_code=400,
        )

    db.add(
        SurveyResponse(
            id=uuid.uuid4().hex,
            terac_submission_id=submission_id or None,
            catalog_json=json.dumps(catalog),
            pitch=pitch,
            fee_tone=fee_tone,
        )
    )
    db.commit()

    callback = _callback_url(submission_id, task_id)
    if callback:
        return RedirectResponse(callback, status_code=303)
    return HTMLResponse(
        "<!doctype html><meta charset=utf-8><title>Thanks</title>"
        "<p style='font-family:ui-sans-serif,system-ui,sans-serif;margin:2rem'>"
        "Thanks. Recorded. You can close this tab.</p>"
    )
