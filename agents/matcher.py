"""Matcher Band agent.

Pick which listed inventory item should fill a borrow request. Coordinate in the loan
room; never initiate refunds or payment actions.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

_CUSTOM_SECTION = """
You are the RigShare Matcher agent. When a borrower asks for gear, pick the best
listed item that satisfies the request. Reply in the Band room with your choice and
brief rationale. Never initiate refunds, settlements, or Stripe actions.
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
    agent_id = settings.band_matcher_agent_id
    api_key = settings.band_matcher_api_key
    if not agent_id or not api_key:
        logger.warning("matcher: BAND_MATCHER_AGENT_ID or BAND_MATCHER_API_KEY missing; skipping")
        return

    if not settings.pioneer_api_key:
        logger.warning("matcher: PIONEER_API_KEY missing; skipping")
        return

    try:
        from band_sdk.agent import Agent
        from band_sdk.adapter.langgraph import LangGraphAdapter
        from langchain_openai import ChatOpenAI
        from langgraph.checkpoint.memory import InMemorySaver
    except ImportError:
        logger.warning("matcher: band-sdk stack not installed; skipping")
        return

    llm = ChatOpenAI(
        model=_decoder_model(settings),
        base_url="https://api.pioneer.ai/v1",
        api_key=settings.pioneer_api_key,
    )
    adapter = LangGraphAdapter(
        llm=llm,
        checkpointer=InMemorySaver(),
        custom_section=_CUSTOM_SECTION,
    )
    agent = Agent.create(
        adapter=adapter,
        agent_id=agent_id,
        api_key=api_key,
    )

    logger.info("matcher: starting Band agent %s", agent_id)
    await agent.run()
