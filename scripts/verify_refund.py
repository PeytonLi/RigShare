#!/usr/bin/env python3
"""Verify the refund state on the test PI. Read-only."""

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PI = "pi_3U4ooqGfsyy6sNDJ17NLN8ov"


def load_env():
    env = {}
    for line in (ROOT / ".env").read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()
    return env


def main():
    env = load_env()
    key = env["STRIPE_SECRET_KEY"]
    req = urllib.request.Request(
        f"https://api.stripe.com/v1/payment_intents/{PI}",
        headers={"Authorization": f"Bearer {key}"},
    )
    with urllib.request.urlopen(req, timeout=25) as r:
        body = json.loads(r.read().decode())
    refunds = body.get("charges", {}).get("data", [{}])[0].get("refunds", {}).get("data", [])
    print(json.dumps({
        "id": body.get("id"),
        "amount": body.get("amount"),
        "amount_refunded": body.get("amount_received") - body.get("amount_captured", 0),
        "status": body.get("status"),
        "charges": [{"id": c.get("id"), "refunded": c.get("refunded"),
                     "refunds": [r.get("id") for r in c.get("refunds", {}).get("data", [])]}
                    for c in body.get("charges", {}).get("data", [])],
    }, indent=2))


if __name__ == "__main__":
    sys.exit(main())
