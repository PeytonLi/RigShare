"""Render worker: run Matcher, Condition, and Clerk Band agents concurrently."""

from __future__ import annotations

import asyncio
import logging

from agents import clerk, condition, matcher

logging.basicConfig(level=logging.INFO)


def main() -> None:
    asyncio.run(_amain())


async def _amain() -> None:
    print("rigshare-agents worker started")
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
