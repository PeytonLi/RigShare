#!/usr/bin/env python3
"""Check Linq payment provider status and iMessage capability. Read-only."""

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

    print("=== provider status: stripe ===")
    code, body = http(f"{LINQ}/payments/providers/stripe", h)
    print(f"http={code}", json.dumps(body, indent=2))

    print("\n=== provider status: agentcard ===")
    code, body = http(f"{LINQ}/payments/providers/agentcard", h)
    print(f"http={code}", json.dumps(body, indent=2))

    print("\n=== iMessage capability check for borrower + lender ===")
    for phone in (env.get("TEST_BORROWER_PHONE"), env.get("LENDER_PHONE")):
        code, body = http(
            f"{LINQ}/capability/check_imessage",
            h,
            data={"address": phone, "from": env.get("LINQ_FROM_NUMBER")},
        )
        print(f"{phone} http={code}", json.dumps(body, indent=2))


if __name__ == "__main__":
    sys.exit(main())
