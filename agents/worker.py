"""Render worker: run Matcher, Condition, and Clerk Band agents concurrently."""

from __future__ import annotations

import asyncio
import logging

from agents import clerk, condition, matcher

logging.basicConfig(level=logging.INFO)


def main() -> None:
    from agents.sdk import load_band_stack

    try:
        load_band_stack()
    except ImportError:
        logging.getLogger(__name__).exception(
            "band-sdk[langgraph] failed to import; worker cannot start"
        )
        raise SystemExit(1)
    asyncio.run(_amain())


def _key_status() -> str:
    from app.config import get_settings

    settings = get_settings()
    flags = {
        "matcher": bool(settings.band_matcher_agent_id and settings.band_matcher_api_key),
        "condition": bool(settings.band_condition_agent_id and settings.band_condition_api_key),
        "clerk": bool(settings.band_clerk_agent_id and settings.band_clerk_api_key),
        "pioneer": bool(settings.pioneer_api_key),
    }
    return " ".join(f"{name}={'yes' if ok else 'NO'}" for name, ok in flags.items())


async def _amain() -> None:
    print("rigshare-agents worker started")
    logging.getLogger(__name__).info("agent env %s", _key_status())
    await asyncio.gather(
        matcher.run(),
        condition.run(),
        clerk.run(),
        return_exceptions=True,
    )
    # if all returned immediately, idle so Render does not restart-loop
    while True:
        await asyncio.sleep(60)


if __name__ == "__main__":
    main()
