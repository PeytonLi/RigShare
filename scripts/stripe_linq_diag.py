#!/usr/bin/env python3
"""Read-only diagnostic for the RigShare Stripe/Linq money path.

Fetches Linq payment requests and Stripe state. Never creates or mutates anything.
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LINQ = "https://api.linqapp.com/api/partner/v3"


def load_env():
    env = {}
    path = ROOT / ".env"
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()
    return env


def http(url, headers=None, data=None, method=None):
    body = None
    if data is not None:
        body = urllib.parse.urlencode(data).encode() if isinstance(data, dict) else data
    headers = {"User-Agent": "rigshare-diag/1.0", **(headers or {})}
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return r.status, json.loads(r.read().decode(errors="replace"))
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode(errors="replace"))
        except ValueError:
            return e.code, {}
    except Exception as e:
        return 0, {"error": str(e)}


def main():
    env = load_env()
    lkey = env.get("LINQ_API_KEY")
    skey = env.get("STRIPE_SECRET_KEY")
    lh = {"Authorization": f"Bearer {lkey}"}
    sh = {"Authorization": f"Bearer {skey}"}

    print("=== Stripe account the key points at ===")
    code, acct = http("https://api.stripe.com/v1/account", sh)
    print(f"http={code}", json.dumps({
        "id": acct.get("id"),
        "business": (acct.get("business_profile") or {}).get("name"),
        "charges_enabled": acct.get("charges_enabled"),
        "payouts_enabled": acct.get("payouts_enabled"),
        "mode": "live" if skey.startswith("sk_live_") else "test",
    }, indent=2))

    print("\n=== Known PI check ===")
    code, body = http(
        "https://api.stripe.com/v1/payment_intents/pi_3U4mrXQbXfHT4Udn0JX2GDdb", sh
    )
    print(f"GET pi_3U4mrXQbXfHT4Udn0JX2GDdb -> http={code}")
    if code == 200:
        print(json.dumps({"id": body.get("id"), "amount": body.get("amount"),
                          "status": body.get("status"),
                          "account": body.get("account")}, indent=2))
    else:
        print("error:", body.get("error", {}).get("message", body))

    print("\n=== Linq payment requests (first 20) ===")
    code, body = http(f"{LINQ}/payment_requests?limit=20", lh)
    print(f"http={code}")
    reqs = body.get("payment_requests", body.get("data", [])) if isinstance(body, dict) else []
    if isinstance(reqs, list):
        for r in reqs[:20]:
            print(json.dumps({
                "id": r.get("id"),
                "amount": r.get("amount"),
                "currency": r.get("currency"),
                "status": r.get("status"),
                "stripe_payment_intent_id": r.get("stripe", {}).get("payment_intent_id")
                    or r.get("payment_intent_id"),
                "checkout_url": r.get("checkout_url"),
                "metadata": r.get("metadata"),
            }, indent=2))
    else:
        print(body)

    print("\n=== Linq org / phone numbers ===")
    code, body = http(f"{LINQ}/phone_numbers", lh)
    print(f"http={code}", json.dumps(body.get("phone_numbers"), indent=2))

    print("\n=== Stripe transfers & charges (empty if Linq money never reaches us) ===")
    code, body = http("https://api.stripe.com/v1/transfers?limit=5", sh)
    print(f"transfers http={code} count={len(body.get('data', [])) if isinstance(body, dict) else 0}")
    code, body = http("https://api.stripe.com/v1/charges?limit=5", sh)
    print(f"charges http={code} count={len(body.get('data', [])) if isinstance(body, dict) else 0}")


if __name__ == "__main__":
    sys.exit(main())
