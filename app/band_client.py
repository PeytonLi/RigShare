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
        # Human API is Enterprise-only ("plan_required"). On any other plan this
        # 403s, so it must not take the agent path down with it -- that failure
        # left every loan with no Band room at all.
        if settings.band_human_api_key:
            try:
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
            except Exception:
                log.info("Band human API unavailable (needs Enterprise); using agent room")
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


def _agents() -> list[tuple[str, str, str]]:
    """(agent_id, api_key, handle) for every agent we hold credentials for."""
    settings = get_settings()
    trio = (
        (settings.band_matcher_agent_id, settings.band_matcher_api_key, "Matcher"),
        (settings.band_condition_agent_id, settings.band_condition_api_key, "Condition"),
        (settings.band_clerk_agent_id, settings.band_clerk_api_key, "Clerk"),
    )
    return [(a, k, h) for a, k, h in trio if a and k]


def post_room_message(
    room_id: str,
    content: str,
    *,
    mention_agent_id: str | None = None,
    mention_handle: str = "Condition",
    api_key: str | None = None,
) -> bool:
    """Band rejects a message with no mentions ("minItems: 1") and rejects an
    agent mentioning itself ("cannot_mention_self"), so the sender is always
    chosen to be someone other than the agent being addressed.
    """
    agents = _agents()
    if not agents:
        return False

    target = next((a for a in agents if a[0] == mention_agent_id), None)
    if target is None:
        target = next((a for a in agents if a[2] == mention_handle), agents[0])

    sender_key = api_key
    if sender_key is None or sender_key == target[1]:
        sender = next((a for a in agents if a[0] != target[0]), None)
        if sender is None:
            return False
        sender_key = sender[1]

    redacted = redact_pii(content)
    handle = target[2]
    if f"@{handle}" not in redacted:
        redacted = f"@{handle} {redacted}"

    try:
        _request(
            "POST",
            f"/agent/chats/{room_id}/messages",
            sender_key,
            {
                "message": {
                    "content": redacted,
                    "mentions": [{"id": target[0], "handle": handle, "name": handle}],
                }
            },
        )
        return True
    except Exception:
        log.exception("band post failed room=%s", room_id)
        return False
