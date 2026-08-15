"""Clerk Band agent.

On Condition ALLOW, POST settle immediately. Never wait for the lender. Never call Stripe
directly; settlement runs server-side on /internal/clerk-settle.
"""

from __future__ import annotations

import logging
import os

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

    try:
        from band_sdk.agent import Agent
        from band_sdk.adapter.langgraph import LangGraphAdapter
        from langchain_openai import ChatOpenAI
        from langgraph.checkpoint.memory import InMemorySaver
    except ImportError:
        logger.warning("clerk: band-sdk stack not installed; skipping")
        return

    additional_tools = clerk_tools()
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

    logger.info("clerk: starting Band agent %s", agent_id)
    await agent.run()
