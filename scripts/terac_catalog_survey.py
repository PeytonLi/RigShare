#!/usr/bin/env python3
"""Saturday catalog survey: which cables people actually borrow.

    python scripts/terac_catalog_survey.py

Creates a 1-participant general-population survey on the RigShare Terac
project. Screenshot the opportunity and later submissions, then reorder the
Matcher prompt / seed bag from what humans picked.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from app.config import get_settings
from app.terac_client import launch_catalog_survey


def main() -> int:
    get_settings.cache_clear()
    settings = get_settings()
    if not settings.terac_api_key or not settings.terac_project_id:
        print("TERAC_API_KEY / TERAC_PROJECT_ID missing")
        return 1
    opportunity_id = launch_catalog_survey(
        "Which of these have you actually needed to borrow at a hackathon or conference?",
        ["HDMI", "USB-C charger", "Lightning", "dongle", "clicker", "none"],
    )
    if not opportunity_id:
        print("create failed (see logs)")
        return 1
    print(f"launched {opportunity_id}")
    print("https://terac.com")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
