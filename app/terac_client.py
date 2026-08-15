from __future__ import annotations

import logging
from typing import Any

from app.config import get_settings

TERAC_API_BASE = "https://terac.com/api/external/v2"
DISPUTE_PROJECT_NAME = "RigShare disputes"

log = logging.getLogger("rigshare")


class FakeTerac:
    def __init__(self) -> None:
        self.opportunities: list[dict] = []
        self.approved: list[str] = []
        self.submissions: dict[str, list[dict]] = {}

    def open_dispute(self, loan_id: str, dispute_url: str) -> str:
        opportunity_id = f"opp_{loan_id}"
        self.opportunities.append({"id": opportunity_id, "loan_id": loan_id, "url": dispute_url})
        return opportunity_id

    def list_submissions(self, opportunity_id: str) -> list[dict]:
        return self.submissions.get(opportunity_id, [])

    def approve_submission(self, submission_id: str) -> None:
        self.approved.append(submission_id)

    def launch_catalog_survey(self, question: str, options: list[str]) -> str:
        opportunity_id = f"opp_survey_{len(self.opportunities)}"
        self.opportunities.append({"id": opportunity_id, "question": question, "options": options})
        return opportunity_id


_gateway: FakeTerac | None = None


def set_terac_gateway(gateway: FakeTerac | None) -> None:
    global _gateway
    _gateway = gateway


def _request(method: str, path: str, payload: dict | None = None) -> dict:
    import httpx

    settings = get_settings()
    response = httpx.request(
        method,
        f"{TERAC_API_BASE}{path}",
        headers={
            "Authorization": f"Bearer {settings.terac_api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=20.0,
    )
    response.raise_for_status()
    data = response.json()
    return data if isinstance(data, dict) else {"data": data}


def _id(data: dict) -> str:
    inner = data.get("data")
    if isinstance(inner, dict):
        data = inner
    return str(data.get("id") or data.get("opportunity_id") or "")


# Terac rejects any study under a $5.00 budget, and 1 participant x 2 minutes
# prices at $3.00 -- so PRD 7.5's "1 participant" can never be created. Two is
# the cheapest configuration that launches; Clerk uses whichever verdict lands
# first, so the second worker only costs money, not time.
MIN_PARTICIPANTS = 2
TASK_MINUTES = 2


def _dispute_project_id() -> str:
    project_id = get_settings().terac_project_id
    if project_id:
        return project_id
    return _id(_request("POST", "/projects", {"title": DISPUTE_PROJECT_NAME}))


def _create_and_launch(payload: dict) -> str | None:
    """A created opportunity recruits nobody until it is launched."""
    opportunity_id = _id(_request("POST", "/opportunities", payload))
    if not opportunity_id:
        return None
    _request("POST", f"/opportunities/{opportunity_id}/launch", {})
    return opportunity_id


def open_dispute(loan_id: str, dispute_url: str) -> str | None:
    """Unmoderated opportunity whose one Activity task is our /disputes page."""
    if _gateway is not None:
        return _gateway.open_dispute(loan_id, dispute_url)
    if not get_settings().terac_api_key:
        log.warning("TERAC_API_KEY not set; skipping openDispute for loan %s", loan_id)
        return None
    try:
        return _create_and_launch(
            {
                "project_id": _dispute_project_id(),
                "title": f"RigShare return dispute {loan_id}",
                "business_type": "b2c",
                "moderated": False,
                "unrestricted_audience": True,
                "num_participants": MIN_PARTICIPANTS,
                "tasks": [
                    {
                        "sequence": 1,
                        "task_type": "activity",
                        "review_type": "manual_review",
                        "title": "Compare two photos of a returned cable",
                        "description": "Two photos, one loan. Tell us if it is the same item.",
                        "task_url": dispute_url,
                        "duration_minutes": TASK_MINUTES,
                    }
                ],
            }
        )
    except Exception:
        log.exception("Terac openDispute failed for loan %s", loan_id)
        return None


def list_submissions(opportunity_id: str) -> list[dict]:
    if _gateway is not None:
        return _gateway.list_submissions(opportunity_id)
    if not get_settings().terac_api_key:
        log.warning("TERAC_API_KEY not set; no submissions for %s", opportunity_id)
        return []
    try:
        data = _request("GET", f"/opportunities/{opportunity_id}/submissions")
    except Exception:
        log.exception("Terac list_submissions failed for %s", opportunity_id)
        return []
    for key in ("submissions", "data", "results"):
        value: Any = data.get(key)
        if isinstance(value, list):
            return [row for row in value if isinstance(row, dict)]
    return []


def approve_submission(submission_id: str) -> None:
    """Approving is what actually pays the human. Never raise into a request path."""
    if _gateway is not None:
        _gateway.approve_submission(submission_id)
        return
    if not get_settings().terac_api_key:
        log.warning("TERAC_API_KEY not set; cannot approve submission %s", submission_id)
        return
    try:
        _request("POST", f"/submissions/{submission_id}/approve", {})
    except Exception:
        log.exception("Terac approve_submission failed for %s", submission_id)


def launch_catalog_survey(question: str, options: list[str]) -> str | None:
    if _gateway is not None:
        return _gateway.launch_catalog_survey(question, options)
    if not get_settings().terac_api_key:
        log.warning("TERAC_API_KEY not set; skipping catalog survey")
        return None
    try:
        return _create_and_launch(
            {
                "project_id": _dispute_project_id(),
                "title": "RigShare catalog check",
                "business_type": "b2c",
                "moderated": False,
                "unrestricted_audience": True,
                "num_participants": MIN_PARTICIPANTS,
                "tasks": [
                    {
                        "sequence": 1,
                        # task_type only accepts interview/file_upload/activity,
                        # so the survey is an activity pointed at our own page.
                        "task_type": "activity",
                        "review_type": "auto_approve",
                        "title": question,
                        "description": " / ".join(options),
                        "task_url": f"{get_settings().public_base_url}/survey",
                        "duration_minutes": TASK_MINUTES,
                    }
                ],
            }
        )
    except Exception:
        log.exception("Terac launch_catalog_survey failed")
        return None


COMPANY_PARTICIPANTS = 10
COMPANY_MINUTES = 3


def launch_company_survey() -> str | None:
    """Growth + Product + Counsel: catalog, pitch, fee. Hosted at /survey.

    Creates and launches. Do not call until PUBLIC_BASE_URL/survey is reachable.
    """
    if _gateway is not None:
        return _gateway.launch_catalog_survey(
            "You forgot a cable.",
            ["USB-C charger", "Lightning", "HDMI", "dongle", "clicker", "none"],
        )
    if not get_settings().terac_api_key:
        log.warning("TERAC_API_KEY not set; skipping company survey")
        return None
    try:
        return _create_and_launch(
            {
                "project_id": _dispute_project_id(),
                "title": "RigShare: what would you borrow, and is the fee fair?",
                "business_type": "b2c",
                "moderated": False,
                "unrestricted_audience": True,
                "num_participants": COMPANY_PARTICIPANTS,
                "tasks": [
                    {
                        "sequence": 1,
                        "task_type": "activity",
                        "review_type": "manual_review",
                        "title": "Three taps: catalog, pitch, fee",
                        "description": (
                            "What you have actually needed to borrow at an event, "
                            "which opening text you would reply to, and whether "
                            "a $2 fee on a $25 hold feels fair."
                        ),
                        "task_url": f"{get_settings().public_base_url.rstrip('/')}/survey",
                        "duration_minutes": COMPANY_MINUTES,
                    }
                ],
            }
        )
    except Exception:
        log.exception("Terac launch_company_survey failed")
        return None
