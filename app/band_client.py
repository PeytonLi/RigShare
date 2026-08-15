from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from app.config import get_settings
from app.pioneer_client import redact_pii

log = logging.getLogger("rigshare")

BAND_BASE = "https://app.band.ai/api/v1"

_http: Callable[[str, str, dict[str, str], dict[str, Any] | None], dict[str, Any]] | None = None


def set_http(
    fn: Callable[[str, str, dict[str, str], dict[str, Any] | None], dict[str, Any]] | None,
) -> None:
    global _http
    _http = fn


def _headers(api_key: str) -> dict[str, str]:
    return {
        "X-API-Key": api_key,
        "Content-Type": "application/json",
        "User-Agent": "rigshare/1.0",
    }


def _request(method: str, path: str, api_key: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    if _http is not None:
        return _http(method, path, _headers(api_key), body)
    import httpx

    response = httpx.request(
        method,
        f"{BAND_BASE}{path}",
        headers=_headers(api_key),
        json=body,
        timeout=20.0,
    )
    response.raise_for_status()
    if not response.content:
        return {}
    return response.json()


def _room_id_from(payload: dict[str, Any]) -> str | None:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    if not isinstance(data, dict):
        return None
    value = data.get("id") or data.get("chat_id")
    return str(value) if value else None


def create_loan_room(loan_id: str, title: str | None = None) -> str | None:
    """One Band room per loan. Human owns it when we have that key; else Matcher."""
    settings = get_settings()
    room_title = title or f"loan-{loan_id[:8]}"
    try:
        if settings.band_human_api_key:
            created = _request(
                "POST",
                "/me/chats",
                settings.band_human_api_key,
                {"title": room_title},
            )
            room_id = _room_id_from(created)
            if room_id:
                for agent_id in (
                    settings.band_matcher_agent_id,
                    settings.band_condition_agent_id,
                    settings.band_clerk_agent_id,
                ):
                    if agent_id:
                        _request(
                            "POST",
                            f"/me/chats/{room_id}/participants",
                            settings.band_human_api_key,
                            {"agent_id": agent_id},
                        )
                return room_id
        if not settings.band_matcher_api_key:
            return None
        created = _request(
            "POST",
            "/agent/chats",
            settings.band_matcher_api_key,
            {"chat": {"title": room_title}},
        )
        room_id = _room_id_from(created)
        if not room_id:
            return None
        for agent_id in (settings.band_condition_agent_id, settings.band_clerk_agent_id):
            if agent_id:
                _request(
                    "POST",
                    f"/agent/chats/{room_id}/participants",
                    settings.band_matcher_api_key,
                    {"participant": {"participant_id": agent_id}},
                )
        return room_id
    except Exception:
        log.exception("band create room failed loan=%s", loan_id)
        return None


def post_room_message(
    room_id: str,
    content: str,
    *,
    mention_agent_id: str | None = None,
    mention_handle: str = "Condition",
    api_key: str | None = None,
) -> bool:
    settings = get_settings()
    key = api_key or settings.band_matcher_api_key or settings.band_clerk_api_key
    if not key:
        return False
    redacted = redact_pii(content)
    mentions = []
    if mention_agent_id:
        mentions.append(
            {
                "id": mention_agent_id,
                "handle": mention_handle,
                "name": mention_handle,
            }
        )
        if f"@{mention_handle}" not in redacted:
            redacted = f"@{mention_handle} {redacted}"
    try:
        _request(
            "POST",
            f"/agent/chats/{room_id}/messages",
            key,
            {"message": {"content": redacted, "mentions": mentions}},
        )
        return True
    except Exception:
        log.exception("band post failed room=%s", room_id)
        return False
