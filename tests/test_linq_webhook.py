from __future__ import annotations

import json
import time

import pytest

from app.linq_webhook import (
    WebhookError,
    event_id,
    event_type,
    inbound_chat_id,
    inbound_from_phone,
    inbound_media_ids,
    inbound_text,
    parse_event,
    verify_linq_signature,
)
from tests.helpers import TEST_WEBHOOK_SECRET, dumps, message_received_payload, sign_linq_body


def test_valid_signature_accepts() -> None:
    body = dumps(message_received_payload())
    headers = sign_linq_body(body)
    verify_linq_signature(TEST_WEBHOOK_SECRET, body, headers)


def test_tampered_body_rejects() -> None:
    body = dumps(message_received_payload(text="hello"))
    headers = sign_linq_body(body)
    tampered = dumps(message_received_payload(text="goodbye"))
    with pytest.raises(WebhookError):
        verify_linq_signature(TEST_WEBHOOK_SECRET, tampered, headers)


def test_wrong_secret_rejects() -> None:
    body = dumps(message_received_payload())
    headers = sign_linq_body(body)
    with pytest.raises(WebhookError):
        verify_linq_signature("whsec_" + "x" * 44, body, headers)


def test_stale_timestamp_rejects() -> None:
    body = dumps(message_received_payload())
    old_ts = int(time.time()) - 600
    headers = sign_linq_body(body, ts=old_ts)
    with pytest.raises(WebhookError):
        verify_linq_signature(TEST_WEBHOOK_SECRET, body, headers)


def test_parse_message_received_2026_02_03() -> None:
    payload = message_received_payload(
        text="Need a 35mm lens",
        chat_id="chat_abc",
        from_phone="+17034051525",
        event_id="evt_2026",
    )
    body = dumps(payload)
    event = parse_event(body)

    assert event_type(event) == "message.received"
    assert event_id(event) == "evt_2026"
    assert inbound_text(event) == "Need a 35mm lens"
    assert inbound_chat_id(event) == "chat_abc"
    assert inbound_from_phone(event) == "+17034051525"
    assert inbound_media_ids(event) == []


def test_parse_message_received_2025_01_01_shape() -> None:
    payload = {
        "api_version": "v3",
        "webhook_version": "2025-01-01",
        "event_type": "message.received",
        "event_id": "evt_2025",
        "created_at": "2026-08-15T20:00:00Z",
        "data": {
            "chat_id": "chat_legacy",
            "from": "+14155551212",
            "message": {
                "parts": [
                    {"type": "text", "value": "legacy hello"},
                    {"type": "media", "id": "media_1"},
                    {"type": "media", "value": "media_2"},
                ]
            },
        },
    }
    event = parse_event(dumps(payload))

    assert event_type(event) == "message.received"
    assert event_id(event) == "evt_2025"
    assert inbound_text(event) == "legacy hello"
    assert inbound_chat_id(event) == "chat_legacy"
    assert inbound_from_phone(event) == "+14155551212"
    assert inbound_media_ids(event) == ["media_1", "media_2"]


def test_verify_accepts_mixed_case_headers() -> None:
    body = dumps(message_received_payload())
    headers = sign_linq_body(body)
    mixed = {
        "Webhook-Id": headers["webhook-id"],
        "WEBHOOK-TIMESTAMP": headers["webhook-timestamp"],
        "webhook-signature": headers["webhook-signature"],
    }
    verify_linq_signature(TEST_WEBHOOK_SECRET, body, mixed)


def test_parse_event_invalid_json_raises() -> None:
    with pytest.raises(json.JSONDecodeError):
        parse_event(b"not-json")
