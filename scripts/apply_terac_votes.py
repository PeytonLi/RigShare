#!/usr/bin/env python3
"""Turn stored /survey votes into live SKU order, pitch, and fee copy.

    python scripts/apply_terac_votes.py

Screenshot the dashboard tallies first. This writes product_state.json and
data/catalog_weights.json. POSTs /internal/apply-votes if PUBLIC_BASE_URL
and INTERNAL_SETTLE_SECRET are set; otherwise applies against the local DB.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")


def _via_http() -> int:
    import os

    import httpx

    base = (os.environ.get("PUBLIC_BASE_URL") or "").rstrip("/")
    secret = os.environ.get("INTERNAL_SETTLE_SECRET") or ""
    if not base or not secret:
        return 2
    response = httpx.post(
        f"{base}/internal/apply-votes",
        headers={"X-Internal-Secret": secret},
        timeout=20.0,
    )
    print(response.status_code)
    print(response.text)
    return 0 if response.is_success else 1


def _via_db() -> int:
    from dataclasses import asdict

    from app.db import SessionLocal, init_db
    from app.desks import record_desk
    from app.product import apply_votes

    init_db()
    db = SessionLocal()
    try:
        state = apply_votes(db)
        record_desk(db, "growth", state.growth_detail)
        record_desk(db, "product", state.product_detail)
        db.commit()
        print(json.dumps(asdict(state), indent=2))
        return 0
    finally:
        db.close()


def main() -> int:
    http_status = _via_http()
    if http_status != 2:
        return http_status
    return _via_db()


if __name__ == "__main__":
    raise SystemExit(main())
