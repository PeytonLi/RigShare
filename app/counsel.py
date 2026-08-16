"""Counsel desk: refuse listings the company will not hold.

Not a fourth Band agent. Matcher/Clerk cite this. The refuse list already lived
in `skus.prohibited_item` and `money.quote`; this names the department.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.money import MoneyQuote, PriceRejected, quote
from app.replies import render
from app.skus import prohibited_item


@dataclass(frozen=True)
class CounselDecision:
    allowed: bool
    reason: str | None
    message: str
    money: MoneyQuote | None = None


def review_listing(
    text: str,
    sku: str | None,
    *,
    demo: bool = False,
    deposit_cents: int | None = None,
    rental_cents: int | None = None,
) -> CounselDecision:
    banned = prohibited_item(text)
    if banned is not None:
        return CounselDecision(
            allowed=False,
            reason=banned,
            message=render("counsel_prohibited", banned=banned),
        )
    try:
        money = quote(
            sku,
            demo=demo,
            deposit_cents=deposit_cents,
            rental_cents=rental_cents,
        )
    except PriceRejected as exc:
        return CounselDecision(
            allowed=False,
            reason="price",
            message=render("counsel_price", reason=str(exc)),
        )
    return CounselDecision(allowed=True, reason=None, message="", money=money)
