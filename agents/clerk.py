"""Clerk Band agent.

After Condition ALLOW and the lender confirms, POST settle to RigShare. Never call Stripe
directly; settlement runs server-side on /internal/clerk-settle.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

_CUSTOM_SECTION = """
You are the RigShare Clerk agent. Wait for Condition ALLOW, then @mention the lender
human for approval. When the lender confirms, call clerk_settle with the loan_id and
event_id from the room context. Never call Stripe or refund APIs yourself.
"""


def _decoder_model(settings) -> str:
    return (
        getattr(settings, "pioneer_decoder_model_id", None)
        or os.getenv("PIONEER_DECODER_MODEL_ID")
        or "claude-haiku-4-5"
    )


def _clerk_tools() -> list:
    try:
        from band_sdk.types import tool
    except ImportError:
        try:
            from langchain_core.tools import tool
        except ImportError:
            return []

    import httpx

    from app.config import get_settings

    @tool
    def clerk_settle(loan_id: str, event_id: str) -> str:
        """POST {PUBLIC_BASE_URL}/internal/clerk-settle after lender approval. Never Stripe."""
        settings = get_settings()
        url = f"{settings.public_base_url.rstrip('/')}/internal/clerk-settle"
        response = httpx.post(
            url,
            headers={"X-Internal-Secret": settings.internal_settle_secret},
            json={"loan_id": loan_id, "event_id": event_id},
            timeout=30.0,
        )
        response.raise_for_status()
        return f"clerk-settle accepted for loan {loan_id}"

    return [clerk_settle]


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

    additional_tools = _clerk_tools()
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
