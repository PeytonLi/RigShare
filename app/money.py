from __future__ import annotations

from dataclasses import dataclass

from app.config import get_settings
from app.skus import SKUS


@dataclass(frozen=True)
class MoneyQuote:
    deposit_cents: int
    rental_cents: int
    platform_fee_cents: int
    refund_cents: int
    sku: str | None


def refund_cents(deposit_cents: int, rental_cents: int, platform_fee_cents: int) -> int:
    return deposit_cents - rental_cents - platform_fee_cents


def assert_money_invariant(
    deposit_cents: int,
    rental_cents: int,
    platform_fee_cents: int,
) -> None:
    if rental_cents + platform_fee_cents >= deposit_cents:
        raise ValueError(
            "rental_cents + platform_fee_cents must be less than deposit_cents"
        )
    if refund_cents(deposit_cents, rental_cents, platform_fee_cents) < 0:
        raise ValueError("refund_cents must be non-negative")


def quote(sku: str | None, *, demo: bool = False) -> MoneyQuote:
    # Read from settings, not module constants: PRD 4.1 wants these per-env so a
    # nervous judge can be dropped to DEMO_* without a code change.
    settings = get_settings()
    if demo:
        deposit = settings.demo_deposit_cents
        rental = settings.demo_rental_cents
        fee = settings.demo_platform_fee_cents
    elif sku is not None and sku in SKUS:
        item = SKUS[sku]
        deposit = item.deposit_cents
        rental = item.rental_cents
        fee = item.platform_fee_cents
    else:
        deposit = settings.default_deposit_cents
        rental = settings.default_rental_cents
        fee = settings.default_platform_fee_cents

    refund = refund_cents(deposit, rental, fee)
    assert_money_invariant(deposit, rental, fee)
    return MoneyQuote(
        deposit_cents=deposit,
        rental_cents=rental,
        platform_fee_cents=fee,
        refund_cents=refund,
        sku=sku,
    )
