from __future__ import annotations

import pytest

from app import terac_client
from app.config import get_settings
from app.terac_client import (
    FakeTerac,
    approve_submission,
    launch_catalog_survey,
    list_submissions,
    open_dispute,
    set_terac_gateway,
)


@pytest.fixture
def fake() -> FakeTerac:
    gateway = FakeTerac()
    set_terac_gateway(gateway)
    yield gateway
    set_terac_gateway(None)


def test_open_dispute_uses_gateway(fake: FakeTerac) -> None:
    opportunity_id = open_dispute("loan-1", "https://rigshare.onrender.com/disputes/loan-1?t=tok")

    assert opportunity_id == "opp_loan-1"
    assert fake.opportunities[0]["url"].endswith("?t=tok")


def test_submissions_and_approve(fake: FakeTerac) -> None:
    fake.submissions["opp_loan-1"] = [{"id": "sub_1", "status": "completed"}]

    assert list_submissions("opp_loan-1") == [{"id": "sub_1", "status": "completed"}]
    assert list_submissions("opp_missing") == []

    approve_submission("sub_1")
    assert fake.approved == ["sub_1"]


def test_catalog_survey_uses_gateway(fake: FakeTerac) -> None:
    opportunity_id = launch_catalog_survey("which cable?", ["HDMI", "USB-C"])

    assert opportunity_id is not None
    assert fake.opportunities[0]["options"] == ["HDMI", "USB-C"]


def test_live_path_creates_then_launches(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TERAC_API_KEY", "terac-key")
    monkeypatch.setenv("TERAC_PROJECT_ID", "proj_1")
    get_settings.cache_clear()
    calls: list[tuple[str, str, dict | None]] = []

    def fake_request(method: str, path: str, payload: dict | None = None) -> dict:
        calls.append((method, path, payload))
        return {"id": "opp_1"}

    monkeypatch.setattr(terac_client, "_request", fake_request)

    assert open_dispute("loan-1", "https://rigshare.onrender.com/disputes/loan-1?t=tok") == "opp_1"

    assert [(m, p) for m, p, _ in calls] == [
        ("POST", "/opportunities"),
        ("POST", "/opportunities/opp_1/launch"),
    ]
    body = calls[0][2] or {}
    assert body["project_id"] == "proj_1"
    assert body["unrestricted_audience"] is True
    assert body["tasks"][0]["task_url"].endswith("?t=tok")


def test_no_api_key_returns_none_and_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TERAC_API_KEY", "")
    get_settings.cache_clear()

    # No gateway either: this is the live path with a missing key.
    assert terac_client._gateway is None
    assert open_dispute("loan-1", "https://example.com/disputes/loan-1?t=tok") is None
    assert list_submissions("opp_1") == []
    assert approve_submission("sub_1") is None
    assert launch_catalog_survey("q", ["a"]) is None
