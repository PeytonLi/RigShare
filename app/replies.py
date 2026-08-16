"""Every outbound iMessage, in one place.

Copy is product, not logic. It gets rewritten between rehearsals, and hunting it
through `if` branches means the demo script and the code drift apart. Rules:

- The template here is the **fallback**, and it is always correct on its own. The
  Pioneer decoder rewrites it (PRD 8, template-first); if the decoder is down or
  garbles a dollar amount, the reader gets exactly this string.
- Slots are named. `{deposit}` arrives pre-formatted ("$15"), so a template can
  never do money math and get it wrong.
"""

from __future__ import annotations

REPLIES: dict[str, str] = {
    # --- refusals -------------------------------------------------------------
    "unsafe": "Can't help with that. If you need a cable, text NEED HDMI / USB-C / LIGHTNING.",
    "lend_no_sku": (
        "What are you lending? Reply LEND HDMI, LEND USB-C, or LEND LIGHTNING. "
        "Orange tape on it."
    ),
    "need_no_sku": "What do you need? NEED HDMI, NEED USB-C, or NEED LIGHTNING.",
    "counsel_prohibited": (
        "Counsel refused: we can't hold a {banned}. RigShare is for cheap gear "
        "people forget. Not that."
    ),
    "counsel_price": "Counsel refused: {reason}",
    "need_none_listed": "Nothing listed for {sku} yet. Ask someone to LEND.",
    # --- listing --------------------------------------------------------------
    "lend_confirm": (
        "Got it. {title}, orange tape. {deposit} hold. You get {rental} when it comes "
        "back. Borrower also pays a {fee} RigShare fee (not taken from you). "
        "Reply YES to list it. Mark the item so we can tell it apart."
    ),
    "yes_nothing_pending": (
        "Nothing waiting to be listed. Text LEND HDMI / USB-C / LIGHTNING with a photo."
    ),
    "yes_listed": (
        "Listed {title}. {deposit} hold on the borrower. You get {rental} when it "
        "comes back."
    ),
    # --- borrowing ------------------------------------------------------------
    "need_matching": "Looking for a {sku} nearby…",
    "need_pay_now": "Pay that link. When it clears, reply PAID.",
    "paid_none_waiting": "No deposit waiting. If you already have the item, reply GOT IT.",
    "paid_not_seen": "I don't see the payment yet. Wait 10 seconds and reply PAID again.",
    "paid_prompt": "If you already paid, reply PAID. If not, use the pay link I sent.",
    "deposit_paid_borrower": "Paid. Meet the lender. When you are holding it, reply GOT IT.",
    "deposit_paid_lender": "Deposit paid. Hand the item over. When they have it, reply GOT IT.",
    "payment_missing_stripe_id": (
        "Payment came in but I still need the Stripe id. Reply PAID in a few seconds."
    ),
    # --- handoff --------------------------------------------------------------
    "got_it_no_loan": "No active loan. Text NEED HDMI / USB-C / LIGHTNING.",
    "got_it_awaiting_deposit": "GOT IT noted. Waiting on the deposit to clear.",
    "got_it_waiting_other": "GOT IT noted. Waiting on the other person.",
    "handoff_holder": "You have it. Return by 2 hours. Photo the orange tape and reply RETURNING.",
    "handoff_other": "Both said GOT IT. Loan is out.",
    "location_ping": "They're on the way: {maps_url}",
    # --- return ---------------------------------------------------------------
    "returning_no_loan": "No active loan to return.",
    "returning_not_out": "That loan is not out yet. Both sides reply GOT IT first.",
    "returning": "Return photo in. Condition is looking at the orange tape.",
    "overdue_borrower": (
        "Your RigShare loan is past due. Reply RETURNING with a photo of the item and "
        "the tape. If it does not come back the deposit is kept."
    ),
    "overdue_lender": "Your item is overdue. We pinged the borrower.",
    # --- settle ---------------------------------------------------------------
    "settle_not_lender": "Only the lender can SETTLE.",
    "settle_no_loan": "No loan to settle.",
    "settle_already_refunded": "Already refunded {refund_id}.",
    "settle_clerk_required": "Clerk has to SETTLE this one in Band first.",
    "settle_no_payment_intent": "No Stripe payment intent on this loan yet. Cannot refund.",
    "settle_blocked": "Cannot settle yet: {reason}",
    "settle_receipt_lender": (
        "Returned. Lender {rental}. RigShare fee {fee}. Refunded {refund}. "
        "It can take a few days to show on the card."
    ),
    "settle_receipt_borrower": (
        "Returned. Refunded {refund}. It can take a few days to show on the card. "
        "You're done."
    ),
    # --- cancel ---------------------------------------------------------------
    "cancel_nothing": "Nothing to cancel.",
    "cancel_done": "Cancelled. Item is listed again.",
}


def render(key: str, **slots: object) -> str:
    """The template with slots filled. KeyError here is a bug, not a runtime case."""
    return REPLIES[key].format(**slots)
