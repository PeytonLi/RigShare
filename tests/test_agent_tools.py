from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from agents.tools import (
    clerk_forfeit,
    clerk_settle,
    hire_inspector,
    pick_item,
    post_condition_verdict,
)

BASE = "https://rigshare.onrender.com"


def _ok_response(text: str = '{"ok": true}') -> MagicMock:
    response = MagicMock()
    response.text = text
    return response


def test_pick_item_posts_url_and_json() -> None:
    response = _ok_response()
    with patch("agents.tools.httpx.post", return_value=response) as mock_post:
        result = pick_item("loan-1", "item-9", "evt-1")

    mock_post.assert_called_once_with(
        f"{BASE}/internal/pick-item",
        headers={"X-Internal-Secret": "test-settle"},
        json={"loan_id": "loan-1", "item_id": "item-9", "event_id": "evt-1"},
        timeout=30.0,
    )
    assert result == '{"ok": true}'


def test_post_condition_verdict_posts_url_and_json() -> None:
    response = _ok_response()
    with patch("agents.tools.httpx.post", return_value=response) as mock_post:
        result = post_condition_verdict("loan-1", "BLOCKED", "evt-2", "wrong object")

    mock_post.assert_called_once_with(
        f"{BASE}/internal/condition-verdict",
        headers={"X-Internal-Secret": "test-settle"},
        json={
            "loan_id": "loan-1",
            "verdict": "BLOCKED",
            "event_id": "evt-2",
            "reason": "wrong object",
        },
        timeout=30.0,
    )
    assert result == '{"ok": true}'


def test_post_condition_verdict_default_reason() -> None:
    response = _ok_response()
    with patch("agents.tools.httpx.post", return_value=response) as mock_post:
        post_condition_verdict("loan-1", "ALLOW", "evt-2")

    assert mock_post.call_args.kwargs["json"]["reason"] == ""


def test_hire_inspector_posts_url_and_json() -> None:
    response = _ok_response()
    with patch("agents.tools.httpx.post", return_value=response) as mock_post:
        result = hire_inspector("loan-1", "evt-3")

    mock_post.assert_called_once_with(
        f"{BASE}/internal/hire-inspector",
        headers={"X-Internal-Secret": "test-settle"},
        json={"loan_id": "loan-1", "event_id": "evt-3"},
        timeout=30.0,
    )
    assert result == '{"ok": true}'


def test_clerk_settle_posts_url_and_json() -> None:
    response = _ok_response()
    with patch("agents.tools.httpx.post", return_value=response) as mock_post:
        result = clerk_settle("loan-1", "evt-4")

    mock_post.assert_called_once_with(
        f"{BASE}/internal/clerk-settle",
        headers={"X-Internal-Secret": "test-settle"},
        json={"loan_id": "loan-1", "event_id": "evt-4"},
        timeout=30.0,
    )
    assert result == '{"ok": true}'


def test_clerk_forfeit_posts_url_and_json() -> None:
    response = _ok_response()
    with patch("agents.tools.httpx.post", return_value=response) as mock_post:
        result = clerk_forfeit("loan-1", "evt-5")

    mock_post.assert_called_once_with(
        f"{BASE}/internal/clerk-forfeit",
        headers={"X-Internal-Secret": "test-settle"},
        json={"loan_id": "loan-1", "event_id": "evt-5"},
        timeout=30.0,
    )
    assert result == '{"ok": true}'


def test_raises_on_http_error() -> None:
    response = MagicMock()
    request = httpx.Request("POST", f"{BASE}/internal/clerk-settle")
    response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "server error",
        request=request,
        response=httpx.Response(500, request=request),
    )
    with patch("agents.tools.httpx.post", return_value=response):
        with pytest.raises(httpx.HTTPStatusError):
            clerk_settle("loan-1", "evt-4")
