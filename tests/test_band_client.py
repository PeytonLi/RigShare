from __future__ import annotations

from app import band_client
from app.config import get_settings


def test_create_loan_room_via_human_api(monkeypatch) -> None:
    monkeypatch.setenv("BAND_HUMAN_API_KEY", "human-key")
    monkeypatch.setenv("BAND_MATCHER_AGENT_ID", "agt_m")
    monkeypatch.setenv("BAND_CONDITION_AGENT_ID", "agt_c")
    monkeypatch.setenv("BAND_CLERK_AGENT_ID", "agt_k")
    get_settings.cache_clear()
    calls: list[tuple[str, str, dict | None]] = []

    def fake_http(method: str, path: str, headers: dict, body: dict | None) -> dict:
        calls.append((method, path, body))
        if path == "/me/chats":
            return {"data": {"id": "room_1"}}
        return {}

    band_client.set_http(fake_http)
    try:
        room_id = band_client.create_loan_room("abcd1234ffff")
    finally:
        band_client.set_http(None)
        get_settings.cache_clear()

    assert room_id == "room_1"
    assert calls[0][1] == "/me/chats"
    added = [path for _, path, _ in calls if path.endswith("/participants")]
    assert len(added) == 3


def test_create_loan_room_noop_without_keys(monkeypatch) -> None:
    monkeypatch.setenv("BAND_HUMAN_API_KEY", "")
    monkeypatch.setenv("BAND_MATCHER_API_KEY", "")
    get_settings.cache_clear()
    band_client.set_http(lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("no http")))
    try:
        assert band_client.create_loan_room("loan") is None
    finally:
        band_client.set_http(None)
        get_settings.cache_clear()


def test_post_room_mentions_condition(monkeypatch) -> None:
    monkeypatch.setenv("BAND_MATCHER_API_KEY", "matcher-key")
    monkeypatch.setenv("BAND_CONDITION_AGENT_ID", "agt_c")
    get_settings.cache_clear()
    posted: list[dict] = []

    def fake_http(method: str, path: str, headers: dict, body: dict | None) -> dict:
        posted.append(body or {})
        return {}

    band_client.set_http(fake_http)
    try:
        assert band_client.post_room_message(
            "room_1",
            "metric 12",
            mention_agent_id="agt_c",
            mention_handle="Condition",
        )
    finally:
        band_client.set_http(None)
        get_settings.cache_clear()

    message = posted[0]["message"]
    assert "@Condition" in message["content"]
    assert message["mentions"][0]["id"] == "agt_c"
