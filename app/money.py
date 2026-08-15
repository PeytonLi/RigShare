from __future__ import annotations

from dataclasses import dataclass

from app.skus import MAX_DEPOSIT_CENTS, MIN_DEPOSIT_CENTS, SKUS

# Product defaults live here, not in Settings/.env. A leftover DEFAULT_* in a
# local env file must not silently change hallway quotes or tests.
DEFAULT_DEPOSIT_CENTS = 2500
DEFAULT_RENTAL_CENTS = 500
DEFAULT_PLATFORM_FEE_CENTS = 200
# Linq's minimum charge. Flip DEMO_MODE=false to restore SKU prices.
DEMO_DEPOSIT_CENTS = 50
DEMO_RENTAL_CENTS = 0
DEMO_PLATFORM_FEE_CENTS = 0


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


class PriceRejected(ValueError):
    """A lender asked for a price we will not hold. Message is customer-facing."""


def _dollars(cents: int) -> str:
    return f"${cents // 100}" if cents % 100 == 0 else f"${cents / 100:.2f}"


def _reject_bad_price(deposit: int, rental: int, fee: int) -> None:
    if deposit > MAX_DEPOSIT_CENTS:
        raise PriceRejected(
            f"{_dollars(deposit)} is over our {_dollars(MAX_DEPOSIT_CENTS)} cap. "
            "RigShare is for cheap gear people forget. Not that."
        )
    if deposit < MIN_DEPOSIT_CENTS:
        raise PriceRejected(
            f"Deposits start at {_dollars(MIN_DEPOSIT_CENTS)}. Try a higher number."
        )
    if rental < 0:
        raise PriceRejected("Rental cannot be negative.")
    if rental + fee >= deposit:
        raise PriceRejected(
            f"The deposit has to be bigger than the rental plus the "
            f"{_dollars(fee)} fee, or there is nothing to refund. "
            f"Try a deposit over {_dollars(rental + fee)}."
        )


def quote(
    sku: str | None,
    *,
    demo: bool = False,
    deposit_cents: int | None = None,
    rental_cents: int | None = None,
) -> MoneyQuote:
    """`deposit_cents`/`rental_cents` are the lender's own numbers when they set them.

    Everything else stays the SKU table. Raises PriceRejected with copy you can text
    straight back, so callers never have to phrase the refusal themselves.
    """
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

    if deposit_cents is not None:
        deposit = deposit_cents
    if rental_cents is not None:
        rental = rental_cents

    if deposit_cents is not None or rental_cents is not None:
        _reject_bad_price(deposit, rental, fee)

    refund = refund_cents(deposit, rental, fee)
    assert_money_invariant(deposit, rental, fee)
    return MoneyQuote(
        deposit_cents=deposit,
        rental_cents=rental,
        platform_fee_cents=fee,
        refund_cents=refund,
        sku=sku,
    )
