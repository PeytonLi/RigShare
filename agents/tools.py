"""Shared HTTP helpers and Band/LangChain tool wrappers for RigShare agents.

Plain functions POST to the internal API and are used by tests without the Band SDK.
"""

from __future__ import annotations

import httpx


def _post(path: str, body: dict) -> str:
    from app.config import get_settings

    settings = get_settings()
    url = f"{settings.public_base_url.rstrip('/')}{path}"
    response = httpx.post(
        url,
        headers={"X-Internal-Secret": settings.internal_settle_secret},
        json=body,
        timeout=30.0,
    )
    response.raise_for_status()
    return response.text


def pick_item(loan_id: str, item_id: str, event_id: str) -> str:
    return _post(
        "/internal/pick-item",
        {"loan_id": loan_id, "item_id": item_id, "event_id": event_id},
    )


def post_condition_verdict(
    loan_id: str, verdict: str, event_id: str, reason: str = ""
) -> str:
    return _post(
        "/internal/condition-verdict",
        {
            "loan_id": loan_id,
            "verdict": verdict,
            "event_id": event_id,
            "reason": reason,
        },
    )


def hire_inspector(loan_id: str, event_id: str) -> str:
    return _post(
        "/internal/hire-inspector",
        {"loan_id": loan_id, "event_id": event_id},
    )


def clerk_settle(loan_id: str, event_id: str) -> str:
    return _post(
        "/internal/clerk-settle",
        {"loan_id": loan_id, "event_id": event_id},
    )


def clerk_forfeit(loan_id: str, event_id: str) -> str:
    return _post(
        "/internal/clerk-forfeit",
        {"loan_id": loan_id, "event_id": event_id},
    )


def _tool_decorator():
    try:
        from band_sdk.types import tool
    except ImportError:
        try:
            from langchain_core.tools import tool
        except ImportError:
            return None
    return tool


def matcher_tools() -> list:
    deco = _tool_decorator()
    if deco is None:
        return []

    http_pick = pick_item

    @deco
    def pick_item(loan_id: str, item_id: str, event_id: str) -> str:
        """POST /internal/pick-item with loan_id and the item_id of the best listed candidate."""
        return http_pick(loan_id, item_id, event_id)

    return [pick_item]


def condition_tools() -> list:
    deco = _tool_decorator()
    if deco is None:
        return []

    http_verdict = post_condition_verdict

    @deco
    def post_condition_verdict(
        loan_id: str, verdict: str, event_id: str, reason: str = ""
    ) -> str:
        """POST /internal/condition-verdict with verdict ALLOW or BLOCKED. Never refund. Never hire Terac."""
        return http_verdict(loan_id, verdict, event_id, reason)

    return [post_condition_verdict]


def clerk_tools() -> list:
    deco = _tool_decorator()
    if deco is None:
        return []

    http_settle = clerk_settle
    http_hire = hire_inspector
    http_forfeit = clerk_forfeit

    @deco
    def clerk_settle(loan_id: str, event_id: str) -> str:
        """POST /internal/clerk-settle on Condition ALLOW or Terac fine/damaged. Do not wait for the lender. Never Stripe."""
        return http_settle(loan_id, event_id)

    @deco
    def hire_inspector(loan_id: str, event_id: str) -> str:
        """POST /internal/hire-inspector on Condition BLOCKED. Do not invent a fourth agent."""
        return http_hire(loan_id, event_id)

    @deco
    def clerk_forfeit(loan_id: str, event_id: str) -> str:
        """POST /internal/clerk-forfeit after Terac different-item. Never Stripe."""
        return http_forfeit(loan_id, event_id)

    return [clerk_settle, hire_inspector, clerk_forfeit]
