from __future__ import annotations

import pytest

from app import superserve_client
from app.config import get_settings
from app.superserve_client import (
    BLOCK_METRIC,
    FakeSuperserve,
    compare_return,
    create_loan_sandbox,
    inspect_outbound,
    inspect_return,
    is_blocked,
    kill_sandbox,
    set_superserve_gateway,
)


@pytest.fixture
def fake():
    gateway = FakeSuperserve()
    set_superserve_gateway(gateway)
    yield gateway
    set_superserve_gateway(None)


class TestParseAe:
    def test_bare_count(self) -> None:
        assert superserve_client._parse_ae("144032\n") == 144032

    def test_count_with_normalized_suffix(self) -> None:
        assert superserve_client._parse_ae("144032 (0.549431)") == 144032

    def test_no_metric(self) -> None:
        assert superserve_client._parse_ae("compare: images differ") is None


class TestIsBlocked:
    def test_small_metric_allows(self) -> None:
        assert is_blocked(0) is False
        assert is_blocked(BLOCK_METRIC - 1) is False

    def test_huge_metric_blocks(self) -> None:
        assert is_blocked(BLOCK_METRIC) is True
        assert is_blocked(BLOCK_METRIC * 2) is True

    def test_unknown_metric_does_not_block(self) -> None:
        assert is_blocked(None) is False


class TestFakeGateway:
    def test_create_then_compare_allows(self, fake: FakeSuperserve) -> None:
        sandbox_id = create_loan_sandbox("loan1", b"outbound")
        assert sandbox_id == "sbx_loan1"
        assert fake.created == [("loan1", b"outbound")]

        fake.metric = 1200
        metric = compare_return(sandbox_id, b"return")
        assert metric == 1200
        assert fake.compared == [("sbx_loan1", b"return")]
        assert is_blocked(metric) is False

    def test_wrong_object_blocks(self, fake: FakeSuperserve) -> None:
        fake.metric = BLOCK_METRIC + 1
        assert is_blocked(compare_return("sbx_loan1", b"water bottle")) is True

    def test_kill(self, fake: FakeSuperserve) -> None:
        kill_sandbox("sbx_loan1")
        assert fake.killed == ["sbx_loan1"]

    def test_inspect_helpers_download_media(self, fake: FakeSuperserve, _fake_linq) -> None:
        _fake_linq.media["m1"] = b"outbound-bytes"
        _fake_linq.media["m2"] = b"return-bytes"
        assert inspect_outbound("loan1", "m1") == "sbx_loan1"
        assert fake.created == [("loan1", b"outbound-bytes")]

        fake.metric = 7
        assert inspect_return("sbx_loan1", "m2") == 7
        assert fake.compared == [("sbx_loan1", b"return-bytes")]

    def test_inspect_helpers_no_media(self, fake: FakeSuperserve) -> None:
        assert inspect_outbound("loan1", None) is None
        assert inspect_return("sbx_loan1", None) is None
        assert inspect_return(None, "m1") is None
        assert fake.created == []
        assert fake.compared == []


class TestNoApiKey:
    """No key must no-op, never crash the webhook path."""

    def test_no_key_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SUPERSERVE_API_KEY", "")
        get_settings.cache_clear()
        assert create_loan_sandbox("loan1", b"outbound") is None
        assert compare_return("sbx_loan1", b"return") is None
        assert kill_sandbox("sbx_loan1") is None
        assert is_blocked(compare_return("sbx_loan1", b"return")) is False
