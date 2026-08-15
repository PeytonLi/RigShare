from __future__ import annotations

from app.config import get_settings

_refunds: list[dict] = []
_next_refund_id = "re_test"


def reset_stripe_fakes() -> None:
    global _refunds, _next_refund_id
    _refunds = []
    _next_refund_id = "re_test"


def refund_payment_intent(payment_intent_id: str, amount_cents: int, *, idempotency_key: str) -> str:
    settings = get_settings()
    if settings.stripe_secret_key.startswith("sk_test_dummy") or settings.stripe_secret_key == "sk_test_dummy":
        _refunds.append(
            {
                "payment_intent_id": payment_intent_id,
                "amount_cents": amount_cents,
                "idempotency_key": idempotency_key,
            }
        )
        return _next_refund_id

    import stripe

    client = stripe.StripeClient(settings.stripe_secret_key)
    refund = client.v1.refunds.create(
        {"payment_intent": payment_intent_id, "amount": amount_cents},
        {"idempotency_key": idempotency_key},
    )
    return str(refund.id)
