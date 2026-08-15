#!/usr/bin/env python3
"""Launch the Saturday morning catalog survey on Terac (PRD 7.5).

    python scripts/terac_catalog_survey.py

General population, 1 participant, 2 minutes, cheap. Prints the opportunity id and
URL. Screenshot the submissions, then reweight Matcher / what you physically bring.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

QUESTION = "Which of these have you actually needed to borrow at a hackathon or conference?"
OPTIONS = ["HDMI cable", "USB-C charger", "Lightning cable", "USB-C dongle", "Presentation clicker", "None of these"]


def main():
    # Settings reads .env, so this works from a bare shell with no exports.
    from app.terac_client import launch_catalog_survey
    from app.config import get_settings

    if not get_settings().terac_api_key:
        print("TERAC_API_KEY missing in .env")
        return 1

    opportunity_id = launch_catalog_survey(QUESTION, OPTIONS)
    if not opportunity_id:
        print("survey launch failed; see log above")
        return 1

    print(f"opportunity_id={opportunity_id}")
    print(f"url=https://terac.com/opportunities/{opportunity_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
