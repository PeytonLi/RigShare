from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from collections.abc import Mapping


class WebhookError(Exception):
    pass


_MAX_AGE_SECONDS = 300


def _header(headers: Mapping[str, str], name: str) -> str | None:
    lower = name.lower()
    for key, value in headers.items():
        if key.lower() == lower:
            return value
    return None


def verify_linq_signature(secret: str, body: bytes, headers: Mapping[str, str]) -> None:
    webhook_id = _header(headers, "webhook-id")
    timestamp = _header(headers, "webhook-timestamp")
    signature = _header(headers, "webhook-signature")

    if not webhook_id or not timestamp or not signature:
        raise WebhookError("missing webhook headers")

    try:
        ts = int(timestamp)
    except ValueError as exc:
        raise WebhookError("invalid webhook timestamp") from exc

    if abs(int(time.time()) - ts) > _MAX_AGE_SECONDS:
        raise WebhookError("webhook timestamp too old")

    key = base64.b64decode(secret.removeprefix("whsec_"))
    signed = f"{webhook_id}.{timestamp}.{body.decode('utf-8')}".encode()
    computed_digest = base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest()).decode()
    for part in signature.split(" "):
        if part.startswith("v1,") and hmac.compare_digest(computed_digest, part[3:]):
            return
    raise WebhookError("invalid webhook signature")


def parse_event(body: bytes) -> dict:
    return json.loads(body)


def _parts(event: dict) -> list[dict]:
    data = event.get("data") or {}
    if isinstance(data.get("parts"), list):
        return data["parts"]
    message = data.get("message") or {}
    if isinstance(message.get("parts"), list):
        return message["parts"]
    return []


def inbound_text(event: dict) -> str | None:
    for part in _parts(event):
        if part.get("type") == "text":
            value = part.get("value")
            if value is not None:
                return str(value)
    return None


def inbound_chat_id(event: dict) -> str | None:
    data = event.get("data") or {}
    chat = data.get("chat") or {}
    chat_id = chat.get("id") or data.get("chat_id")
    return str(chat_id) if chat_id is not None else None


def inbound_from_phone(event: dict) -> str | None:
    data = event.get("data") or {}
    sender = data.get("sender_handle") or {}
    phone = sender.get("handle") or data.get("from")
    return str(phone) if phone is not None else None


_MEDIA_TYPES = {"media", "image", "attachment"}


def inbound_media_ids(event: dict) -> list[str]:
    media_ids: list[str] = []
    for part in _parts(event):
        ptype = str(part.get("type") or "")
        looks_like_file = part.get("url") or part.get("mime_type") or part.get("filename")
        if ptype not in _MEDIA_TYPES and not looks_like_file:
            continue
        if ptype in {"text", "link", "location"}:
            continue
        media_id = part.get("id") or part.get("attachment_id") or part.get("value")
        if media_id is None or str(media_id).startswith("http"):
            continue
        media_ids.append(str(media_id))
    return media_ids


def event_type(event: dict) -> str:
    return str(event.get("event_type") or event.get("type") or "")


def event_id(event: dict) -> str:
    return str(event.get("event_id") or event.get("id") or "")
