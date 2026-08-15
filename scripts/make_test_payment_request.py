#!/usr/bin/env python3
"""Decisive test: create a live $0.50 payment request via Linq.

Creating a request does NOT move money. Paying the checkout_url does.
Run this, then pay the URL from the borrower phone, then run
stripe_linq_diag.py to see whether the charge appears under STRIPE_SECRET_KEY.
"""

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LINQ = "https://api.linqapp.com/api/partner/v3"


def load_env():
    env = {}
    for line in (ROOT / ".env").read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()
    return env


def http(url, headers=None, data=None):
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(
        url, data=body, headers={"User-Agent": "rigshare-diag/1.0", **(headers or {})}
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            raw = r.read().decode(errors="replace")
            try:
                return r.status, json.loads(raw)
            except ValueError:
                return r.status, raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, raw
    except Exception as e:
        return 0, {"error": str(e)}


def main():
    env = load_env()
    key = env["LINQ_API_KEY"]
    h = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    code, body = http(
        f"{LINQ}/payment_requests",
        h,
        data={
            "amount": 50,
            "currency": "usd",
            "description": "RigShare $0.50 refund-path test",
            "from": env.get("LINQ_FROM_NUMBER"),
            "payer_handle": env.get("TEST_BORROWER_PHONE"),
            "metadata": {"loan_id": "refundtest2"},
        },
    )
    print(f"http={code}")
    print(json.dumps(body, indent=2))
    if code == 200:
        print(f"\nPAY THIS URL from the borrower phone:\n{body.get('checkout_url')}")
        print("\nThen run: python scripts/stripe_linq_diag.py")


if __name__ == "__main__":
    sys.exit(main())
