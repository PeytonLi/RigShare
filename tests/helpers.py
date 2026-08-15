from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time


TEST_WEBHOOK_SECRET = "whsec_" + base64.b64encode(b"rigshare-test-webhook-secret-32b").decode()


def sign_linq_body(body: bytes, secret: str = TEST_WEBHOOK_SECRET, *, event_id: str = "evt_test", ts: int | None = None) -> dict[str, str]:
    timestamp = str(ts if ts is not None else int(time.time()))
    key = base64.b64decode(secret.removeprefix("whsec_"))
    signed = f"{event_id}.{timestamp}.{body.decode('utf-8')}".encode()
    digest = base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest()).decode()
    return {
        "webhook-id": event_id,
        "webhook-timestamp": timestamp,
        "webhook-signature": f"v1,{digest}",
    }


def message_received_payload(*, text: str = "hello", chat_id: str = "chat_1", from_phone: str = "+17034051525", event_id: str = "evt_msg_1") -> dict:
    return {
        "api_version": "v3",
        "webhook_version": "2026-02-03",
        "event_type": "message.received",
        "event_id": event_id,
        "created_at": "2026-08-15T20:00:00Z",
        "trace_id": "trace",
        "partner_id": "partner",
        "data": {
            "chat": {"id": chat_id, "is_group": False},
            "id": "msg_1",
            "direction": "inbound",
            "sender_handle": {"handle": from_phone, "is_me": False, "service": "iMessage"},
            "parts": [{"type": "text", "value": text}],
            "service": "iMessage",
        },
    }


def dumps(payload: dict) -> bytes:
    return json.dumps(payload, separators=(",", ":")).encode()
