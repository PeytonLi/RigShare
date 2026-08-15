#!/usr/bin/env python3
"""Launch the 10-person Growth/Product survey after /survey is live.

    python scripts/launch_company_survey.py

Do not run this until GET {PUBLIC_BASE_URL}/survey returns 200. A draft
created in Terac is cheaper to review first; this script creates and launches.
"""

from __future__ import annotations

import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from app.config import get_settings
from app.terac_client import launch_company_survey


def main() -> int:
    get_settings.cache_clear()
    settings = get_settings()
    if not settings.terac_api_key or not settings.terac_project_id:
        print("TERAC_API_KEY / TERAC_PROJECT_ID missing")
        return 1
    survey = f"{settings.public_base_url.rstrip('/')}/survey"
    try:
        check = httpx.get(survey, timeout=15.0, follow_redirects=True)
    except httpx.HTTPError as exc:
        print(f"{survey} unreachable: {exc}")
        return 1
    if check.status_code != 200:
        print(f"{survey} returned {check.status_code}; deploy /survey first")
        return 1
    opportunity_id = launch_company_survey()
    if not opportunity_id:
        print("create failed (see logs)")
        return 1
    print(f"launched {opportunity_id}")
    print(survey)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
