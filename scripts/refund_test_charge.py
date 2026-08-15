#!/usr/bin/env python3
"""Refund the paid $0.50 test charge via Stripe (the final money-path proof)."""

import json
import sys
import urllib.error
import urllib.parse
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
    headers = {"Authorization": f"Bearer {key}"}
    url = "https://api.stripe.com/v1/refunds"
    data = urllib.parse.urlencode({"payment_intent": PI}).encode()
    req = urllib.request.Request(
        url, data=data, headers={**headers, "Content-Type": "application/x-www-form-urlencoded"}
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            body = json.loads(r.read().decode())
            print(f"http={r.status}")
    except urllib.error.HTTPError as e:
        print(f"http={e.code}")
        body = json.loads(e.read().decode())
    pi = body.get("payment_intent") or {}
    if isinstance(pi, dict):
        pi = pi.get("id", pi)
    print(json.dumps({
        "id": body.get("id"),
        "payment_intent": pi,
        "amount": body.get("amount"),
        "currency": body.get("currency"),
        "status": body.get("status"),
    }, indent=2))


if __name__ == "__main__":
    sys.exit(main())
