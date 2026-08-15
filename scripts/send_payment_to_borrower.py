#!/usr/bin/env python3
"""Send the $0.50 payment request to the borrower number as an iMessage/RCS thread.

Flow (Linq rules):
  1. First outbound message in a new chat CANNOT contain links.
  2. So: send an intro text via POST /v3/messages (chat created incidentally, returns chat_id).
  3. Then POST the checkout_url as a link part in a follow-up to that chat_id.
"""

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LINQ = "https://api.linqapp.com/api/partner/v3"

CHECKOUT_URL = (
    "https://zero.linqapp.com/pay/uc-berkeley-sandbox"
    "?session=tok_kdffooalvrvg65ng3i2yvckzgyfagj3u"
)


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
    to = env["TEST_BORROWER_PHONE"]

    print(f"=== step 1: intro message to {to} ===")
    code, body = http(
        f"{LINQ}/messages",
        h,
        data={
            "to": [to],
            "message": {"parts": [{"type": "text", "value": "RigShare is live. Text LEND or NEED to borrow gear."}]},
        },
    )
    print(f"http={code}")
    print(json.dumps(body, indent=2))
    if code not in (200, 201, 202):
        print("intro failed; aborting")
        return

    chat_id = None
    if isinstance(body, dict):
        chat_id = body.get("chat_id") or (body.get("data") or {}).get("chat_id")
        chat = body.get("chat") or {}
        chat_id = chat_id or chat.get("id")
    print(f"chat_id={chat_id}")
    if not chat_id:
        print("no chat_id returned; cannot send link. The chat may already exist.")
        return

    print(f"\n=== step 2: send payment link to chat {chat_id} ===")
    code, body = http(
        f"{LINQ}/chats/{chat_id}/messages",
        h,
        data={"message": {"parts": [{"type": "link", "value": CHECKOUT_URL}]}},
    )
    print(f"http={code}")
    print(json.dumps(body, indent=2))

    if code in (200, 201, 202):
        print(f"\nPAYMENT LINK SENT to {to} in chat {chat_id}")
    else:
        print("\nlink send failed")


if __name__ == "__main__":
    sys.exit(main())
