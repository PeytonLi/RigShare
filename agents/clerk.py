"""Clerk Band agent.

On Condition ALLOW, POST settle immediately. Never wait for the lender. Never call Stripe
directly; settlement runs server-side on /internal/clerk-settle.
"""

from __future__ import annotations

import logging
import os

from agents.sdk import start_band_agent
from agents.tools import clerk_tools

logger = logging.getLogger(__name__)

_CUSTOM_SECTION = """
You are the RigShare Clerk. On Condition ALLOW, immediately call clerk_settle.
Do not wait for the lender. On BLOCKED, call hire_inspector. After Terac
fine or damaged, clerk_settle. After Terac different-item, clerk_forfeit.
Do not invent a fourth agent. Never call Stripe.
"""


def _decoder_model(settings) -> str:
    return (
        getattr(settings, "pioneer_decoder_model_id", None)
        or os.getenv("PIONEER_DECODER_MODEL_ID")
        or "claude-haiku-4-5"
    )


async def run() -> None:
    from app.config import get_settings

    settings = get_settings()
    agent_id = settings.band_clerk_agent_id
    api_key = settings.band_clerk_api_key
    if not agent_id or not api_key:
        logger.warning("clerk: BAND_CLERK_AGENT_ID or BAND_CLERK_API_KEY missing; skipping")
        return

    if not settings.pioneer_api_key:
        logger.warning("clerk: PIONEER_API_KEY missing; skipping")
        return

    await start_band_agent(
        name="clerk",
        agent_id=agent_id,
        api_key=api_key,
        custom_section=_CUSTOM_SECTION,
        additional_tools=clerk_tools(),
        decoder_model=_decoder_model(settings),
        pioneer_api_key=settings.pioneer_api_key,
    )
