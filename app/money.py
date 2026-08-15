from __future__ import annotations

from dataclasses import dataclass

from app.skus import SKUS

# Product defaults live here, not in Settings/.env. A leftover DEFAULT_* in a
# local env file must not silently change hallway quotes or tests.
DEFAULT_DEPOSIT_CENTS = 2500
DEFAULT_RENTAL_CENTS = 500
DEFAULT_PLATFORM_FEE_CENTS = 200
DEMO_DEPOSIT_CENTS = 800
DEMO_RENTAL_CENTS = 200
DEMO_PLATFORM_FEE_CENTS = 100


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
    if demo:
        deposit = DEMO_DEPOSIT_CENTS
        rental = DEMO_RENTAL_CENTS
        fee = DEMO_PLATFORM_FEE_CENTS
    elif sku is not None and sku in SKUS:
        item = SKUS[sku]
        deposit = item.deposit_cents
        rental = item.rental_cents
        fee = item.platform_fee_cents
    else:
        deposit = DEFAULT_DEPOSIT_CENTS
        rental = DEFAULT_RENTAL_CENTS
        fee = DEFAULT_PLATFORM_FEE_CENTS

    refund = refund_cents(deposit, rental, fee)
    assert_money_invariant(deposit, rental, fee)
    return MoneyQuote(
        deposit_cents=deposit,
        rental_cents=rental,
        platform_fee_cents=fee,
        refund_cents=refund,
        sku=sku,
    )
