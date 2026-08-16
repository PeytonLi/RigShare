"""Matcher Band agent.

Pick which listed inventory item should fill a borrow request. Coordinate in the loan
room; never initiate refunds or payment actions.
"""

from __future__ import annotations

import logging
import os

from agents.sdk import start_band_agent
from agents.tools import matcher_tools

logger = logging.getLogger(__name__)

_CUSTOM_SECTION = """
You are the RigShare Matcher agent. When a borrower asks for gear, pick the best
listed item that satisfies the request. Auto-pick prefers higher weight SKUs from
data/catalog_weights.json. Call pick_item(loan_id, item_id, event_id) with your
choice. Reply in the Band room with your choice and brief rationale. Never call
Stripe. Never initiate refunds or settlements. If you only chat a SKU without
calling the tool, the loan stays matching and the borrower never gets a pay link.
"""


def _decoder_model(settings) -> str:
    return (
        getattr(settings, "pioneer_decoder_model_id", None)
        or os.getenv("PIONEER_DECODER_MODEL_ID")
        or "claude-haiku-4-5"
    )


async def run() -> None:
    from app.config import get_settings
    from app.product import matcher_brief

    settings = get_settings()
    agent_id = settings.band_matcher_agent_id
    api_key = settings.band_matcher_api_key
    if not agent_id or not api_key:
        logger.warning("matcher: BAND_MATCHER_AGENT_ID or BAND_MATCHER_API_KEY missing; skipping")
        return

    if not settings.pioneer_api_key:
        logger.warning("matcher: PIONEER_API_KEY missing; skipping")
        return

    await start_band_agent(
        name="matcher",
        agent_id=agent_id,
        api_key=api_key,
        custom_section=_CUSTOM_SECTION + "\n" + matcher_brief(),
        additional_tools=matcher_tools(),
        decoder_model=_decoder_model(settings),
        pioneer_api_key=settings.pioneer_api_key,
    )
