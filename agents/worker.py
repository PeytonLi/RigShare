"""Render worker: run Matcher, Condition, and Clerk Band agents concurrently."""

from __future__ import annotations

import asyncio
import logging
import sys

from agents import clerk, condition, matcher

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s:%(name)s:%(message)s",
    stream=sys.stdout,
    force=True,
)
log = logging.getLogger(__name__)


def main() -> None:
    from agents.sdk import load_band_stack

    try:
        load_band_stack()
    except ImportError:
        log.exception("band-sdk[langgraph] failed to import; worker cannot start")
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


async def _keep(name: str, run) -> None:
    while True:
        try:
            await run()
            log.warning("%s: run() returned; retry in 5s", name)
        except Exception:
            log.exception("%s: crashed; retry in 5s", name)
        await asyncio.sleep(5)


async def _amain() -> None:
    log.info("rigshare-agents worker started")
    log.info("agent env %s", _key_status())
    await asyncio.gather(
        _keep("matcher", matcher.run),
        _keep("condition", condition.run),
        _keep("clerk", clerk.run),
    )


if __name__ == "__main__":
    main()
