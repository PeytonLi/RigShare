from __future__ import annotations

import pytest

from app.money import MoneyQuote, assert_money_invariant, quote, refund_cents
from app.skus import SKUS, get_sku, resolve_sku


class TestRefundCents:
    def test_hdmi_amounts(self) -> None:
        assert refund_cents(1500, 300, 200) == 1000

    def test_default_amounts(self) -> None:
        assert refund_cents(2500, 500, 200) == 1800

    def test_demo_amounts(self) -> None:
        assert refund_cents(50, 0, 0) == 50


class TestAssertMoneyInvariant:
    def test_valid_passes(self) -> None:
        assert_money_invariant(1500, 300, 200)

    def test_rental_plus_fee_equals_deposit_raises(self) -> None:
        with pytest.raises(ValueError):
            assert_money_invariant(500, 300, 200)

    def test_rental_plus_fee_exceeds_deposit_raises(self) -> None:
        with pytest.raises(ValueError):
            assert_money_invariant(400, 300, 200)

    def test_negative_refund_raises(self) -> None:
        with pytest.raises(ValueError):
            assert_money_invariant(300, 200, 200)


class TestQuote:
    def test_hdmi_quote(self) -> None:
        q = quote("hdmi")
        assert q == MoneyQuote(
            deposit_cents=1500,
            rental_cents=300,
            platform_fee_cents=200,
            refund_cents=1000,
            sku="hdmi",
        )

    def test_unknown_sku_defaults(self) -> None:
        q = quote(None)
        assert q.deposit_cents == 2500
        assert q.rental_cents == 500
        assert q.platform_fee_cents == 200
        assert q.refund_cents == 1800
        assert q.sku is None

    def test_unknown_sku_id_defaults(self) -> None:
        q = quote("nonexistent")
        assert q.deposit_cents == 2500
        assert q.rental_cents == 500
        assert q.platform_fee_cents == 200
        assert q.refund_cents == 1800
        assert q.sku == "nonexistent"

    def test_usbc_charger(self) -> None:
        q = quote("usbc_charger")
        assert q.deposit_cents == 2500
        assert q.rental_cents == 500
        assert q.platform_fee_cents == 200
        assert q.refund_cents == 1800

    def test_demo_override(self) -> None:
        q = quote("hdmi", demo=True)
        assert q.deposit_cents == 50
        assert q.rental_cents == 0
        assert q.platform_fee_cents == 0
        assert q.refund_cents == 50
        assert q.sku == "hdmi"


class TestSkus:
    def test_skus_table_has_all_entries(self) -> None:
        expected = {
            "usbc_charger",
            "lightning_cable",
            "usbc_cable",
            "hdmi",
            "usbc_hdmi",
            "usbc_hub",
            "lightning_usbc",
            "clicker",
        }
        assert set(SKUS.keys()) == expected

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("usb-c", "usbc_charger"),
            ("usbc", "usbc_charger"),
            ("charger", "usbc_charger"),
            ("gan", "usbc_charger"),
            ("anker", "usbc_charger"),
            ("NEED USB-C", "usbc_charger"),
            ("lightning", "lightning_cable"),
            ("hdmi", "hdmi"),
            ("dongle", "usbc_hub"),
            ("hub", "usbc_hub"),
            ("multiport", "usbc_hub"),
            ("usb-c to hdmi", "usbc_hdmi"),
            ("usbc hdmi", "usbc_hdmi"),
            ("lightning to usb", "lightning_usbc"),
            ("lightning-usbc", "lightning_usbc"),
        ],
    )
    def test_resolve_sku_aliases(self, text: str, expected: str) -> None:
        assert resolve_sku(text) == expected

    def test_get_sku_returns_pricing(self) -> None:
        sku = get_sku("hdmi")
        assert sku.id == "hdmi"
        assert sku.deposit_cents == 1500
        assert sku.rental_cents == 300
        assert sku.platform_fee_cents == 200
