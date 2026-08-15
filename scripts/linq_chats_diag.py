#!/usr/bin/env python3
"""Check whether any Linq chat/thread exists with the borrower or lender."""

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

    code, body = http(f"{LINQ}/chats", h)
    print(f"GET /chats http={code}")
    chats = body.get("chats", []) if isinstance(body, dict) else []
    print(f"total chats: {len(chats)}")
    borrower = env.get("TEST_BORROWER_PHONE")
    lender = env.get("LENDER_PHONE")
    for c in chats:
        print(json.dumps({
            "id": c.get("id"),
            "service": c.get("service"),
            "handles": c.get("handles") or c.get("participants"),
            "from": c.get("from"),
            "to": c.get("to"),
        }, indent=2))

    print("\n=== does any chat involve the borrower or lender? ===")
    for c in chats:
        blob = json.dumps(c)
        if borrower and borrower in blob:
            print(f"BORROWER {borrower} in chat {c.get('id')}")
        if lender and lender in blob:
            print(f"LENDER {lender} in chat {c.get('id')}")


if __name__ == "__main__":
    sys.exit(main())
