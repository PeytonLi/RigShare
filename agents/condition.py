"""Condition Band agent.

Review outbound/return photo evidence and sandbox metrics. Reply ALLOW or BLOCKED.
Never initiate refunds or payment actions.
"""

from __future__ import annotations

import logging
import os

from agents.sdk import start_band_agent
from agents.tools import condition_tools

logger = logging.getLogger(__name__)

_CUSTOM_SECTION = """
You are the RigShare Condition agent. Inspect return photo URLs and sandbox metric
evidence in the loan room. ImageMagick AE is evidence, not a decision. Call
post_condition_verdict with verdict ALLOW when the returned item matches what went
out, or BLOCKED when evidence shows the wrong item, missing orange tape, or
significant damage. Never refund. Never hire Terac. Never call Stripe.
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
    agent_id = settings.band_condition_agent_id
    api_key = settings.band_condition_api_key
    if not agent_id or not api_key:
        logger.warning("condition: BAND_CONDITION_AGENT_ID or BAND_CONDITION_API_KEY missing; skipping")
        return

    if not settings.pioneer_api_key:
        logger.warning("condition: PIONEER_API_KEY missing; skipping")
        return

    await start_band_agent(
        name="condition",
        agent_id=agent_id,
        api_key=api_key,
        custom_section=_CUSTOM_SECTION,
        additional_tools=condition_tools(),
        decoder_model=_decoder_model(settings),
        pioneer_api_key=settings.pioneer_api_key,
    )
