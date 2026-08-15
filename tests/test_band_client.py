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


def _all_agents(monkeypatch) -> None:
    for name, agent, key in (
        ("MATCHER", "agt_m", "matcher-key"),
        ("CONDITION", "agt_c", "condition-key"),
        ("CLERK", "agt_k", "clerk-key"),
    ):
        monkeypatch.setenv(f"BAND_{name}_AGENT_ID", agent)
        monkeypatch.setenv(f"BAND_{name}_API_KEY", key)
    get_settings.cache_clear()


def _capture(posted: list[tuple[dict, dict]]):
    def fake_http(method: str, path: str, headers: dict, body: dict | None):
        posted.append((headers, body or {}))
        return {}

    return fake_http


def test_post_room_mentions_condition(monkeypatch) -> None:
    _all_agents(monkeypatch)
    posted: list[tuple[dict, dict]] = []
    band_client.set_http(_capture(posted))
    try:
        assert band_client.post_room_message(
            "room_1", "metric 12", mention_agent_id="agt_c", mention_handle="Condition"
        )
    finally:
        band_client.set_http(None)
        get_settings.cache_clear()

    headers, body = posted[0]
    message = body["message"]
    assert "@Condition" in message["content"]
    # Band requires at least one mention and rejects self-mentions, so the
    # sender must be some other agent than the one being addressed.
    assert message["mentions"] == [{"id": "agt_c", "handle": "Condition", "name": "Condition"}]
    assert headers["X-API-Key"] != "condition-key"


def test_post_never_mentions_itself(monkeypatch) -> None:
    """run_quote_and_charge posts as Matcher while addressing Matcher; Band
    answers 422 cannot_mention_self unless the sender is swapped."""
    _all_agents(monkeypatch)
    posted: list[tuple[dict, dict]] = []
    band_client.set_http(_capture(posted))
    try:
        assert band_client.post_room_message(
            "room_1",
            "pick an item",
            mention_agent_id="agt_m",
            mention_handle="Matcher",
            api_key="matcher-key",
        )
    finally:
        band_client.set_http(None)
        get_settings.cache_clear()

    headers, body = posted[0]
    assert body["message"]["mentions"][0]["id"] == "agt_m"
    assert headers["X-API-Key"] != "matcher-key"


def test_post_always_sends_a_mention(monkeypatch) -> None:
    """An empty mentions array is rejected with "minItems: 1"."""
    _all_agents(monkeypatch)
    posted: list[tuple[dict, dict]] = []
    band_client.set_http(_capture(posted))
    try:
        assert band_client.post_room_message("room_1", "no target given")
    finally:
        band_client.set_http(None)
        get_settings.cache_clear()

    mentions = posted[0][1]["message"]["mentions"]
    assert len(mentions) == 1
    assert mentions[0]["id"] == "agt_c"  # defaults to the Condition handle
