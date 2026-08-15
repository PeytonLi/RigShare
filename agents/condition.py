"""Condition Band agent.

Review outbound/return photo evidence and sandbox metrics. Reply ALLOW or BLOCKED.
Never initiate refunds or payment actions.
"""

from __future__ import annotations

import logging
import os

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

    try:
        from band_sdk.agent import Agent
        from band_sdk.adapter.langgraph import LangGraphAdapter
        from langchain_openai import ChatOpenAI
        from langgraph.checkpoint.memory import InMemorySaver
    except ImportError:
        logger.warning("condition: band-sdk stack not installed; skipping")
        return

    additional_tools = condition_tools()
    llm = ChatOpenAI(
        model=_decoder_model(settings),
        base_url="https://api.pioneer.ai/v1",
        api_key=settings.pioneer_api_key,
    )
    adapter = LangGraphAdapter(
        llm=llm,
        checkpointer=InMemorySaver(),
        custom_section=_CUSTOM_SECTION,
        additional_tools=additional_tools or None,
    )
    agent = Agent.create(
        adapter=adapter,
        agent_id=agent_id,
        api_key=api_key,
    )

    logger.info("condition: starting Band agent %s", agent_id)
    await agent.run()
