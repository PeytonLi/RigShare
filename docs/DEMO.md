# RigShare — 4-minute hallway demo

Print this. Every text below is copied from `app/loans.py` as it runs today. If a
reply does not match, the code changed and this page is stale.

**Two iPhones.** Lender phone must be the number in `LENDER_PHONE`
(`+14159909839`) — only that number can `SETTLE`. Borrower is any other iPhone,
ideally the judge's. Both text the Linq number in **iMessage**, 1:1, never a group.

**Laptop windows, in this order left to right:**

1. Dashboard `https://<host>/` (loans + items)
2. Band console, room `loan-<loan_id>`
3. Stripe Dashboard → Payments
4. Render → Workflows → task runs

---

## 0. Before you walk up (60 s, off camera)

- Orange tape on the HDMI. Visible in both photos or Condition will false-block.
- Lender phone: text **`LEND HDMI`** with a photo of the taped cable.
  Expect back:
  > Got it. hdmi, orange tape. $0.50 hold. You get $0 when it comes back. Borrower also pays a $0 RigShare fee (not taken from you). Reply YES to list it. Mark the item so we can tell it apart.
- Item is `pending` at this point and **cannot be borrowed**. Reply **`YES`**:
  > Listed hdmi. $0.50 hold on the borrower. You get $0 when it comes back.
- Dashboard `/` now shows one item, status `listed`. That is your opening shot.

If you skip `YES`, `NEED HDMI` answers "Nothing listed for hdmi yet" — that is the
confirmation gate working, not a bug. `YES` only ever confirms the sender's own
most recent pending listing.

---

## 1. Borrower asks (35 s)

Judge's phone → the Linq number:

```
NEED HDMI
```

Two messages come back, the second is a tappable link:

> hdmi nearby, marked with orange tape. $0.50 hold now. $0 to the lender if you bring it back. $0 RigShare fee. $0.50 refunded.

Prices are $0.50 / $0 / $0 while `DEMO_MODE` is on so anyone can Apple Pay. Set `DEMO_MODE=false` to restore HDMI $15.

**Screen:** dashboard `/` — item flipped to `reserved`, a loan appeared in
`awaiting_deposit`. Render task runs shows `quoteAndCharge`.

---

## 2. Judge pays (45 s)

They tap the link, Apple Pay, done.

Borrower gets:
> Paid. Meet the lender. When you are holding it, reply GOT IT.

Lender gets:
> Deposit paid. Hand the item over. When they have it, reply GOT IT.

Both phones also get an iMessage **location request** prompt. Accepting is
optional — say so, then accept on the lender phone anyway. When either side starts
sharing, the *other* party's thread gets:

> They're on the way: https://maps.google.com/?q=37.7749,-122.4194

Location is decoration. `GOT IT` is the handoff, never GPS.

**Screen:** Stripe → Payments, the $0.50 PaymentIntent, succeeded. Then
`/loans/<id>` showing `walking` and the `pi_...` id. Render shows `onDepositPaid`.

---

## 3. Physical handoff (30 s)

Walk the cable across. Both phones text:

```
GOT IT
```

Whoever is second gets:
> You have it. Return by 2 hours. Photo the orange tape and reply RETURNING.

The other:
> Both said GOT IT. Loan is out.

**Screen:** `/loans/<id>` is `out`, `return_by_at` set. Render shows `onHandoff`.

---

## 4. Return (40 s)

Borrower photographs the cable with the tape showing and texts:

```
RETURNING
```
(attach the photo in the same message)

> Return photo in. Lender: reply SETTLE <loan_id> if it matches (orange tape).

**Screen:** Band room `loan-<id>` — Condition posts `ALLOW` with the ImageMagick
metric. Render shows `inspectReturn`. This is the delete-test slide: Clerk is the
only path to a refund.

---

## 5. Settle (50 s)

Lender phone, copy the loan id out of the message the bot just sent:

```
SETTLE <loan_id>
```

Lender gets:
> Returned. Lender $0. RigShare fee $0. Refunded $0.50. It can take a few days to show on the card.

Borrower gets:
> Returned. Refunded $0.50. It can take a few days to show on the card. You're done.

**Screen:** Stripe → the same PaymentIntent → **Refund $0.50**, `re_...`. Then
`/loans/<id>` showing `closed` with both the `pi_` and `re_` ids. Render shows
`settle`. Card posting takes 5–10 days — show the Refund object, not the card.

Close on the dashboard: item back to `listed`, ready for the next borrower.

---

## Restore real SKU prices

`DEMO_MODE` defaults on: every new `LEND` is $0.50 hold, $0 rental, $0 fee, $0.50
refunded (Linq's minimum). Set `DEMO_MODE=false` on the Render env group and
redeploy, then `LEND` again — old listed rows keep their old cents.

---

## Recovery moves

**The bot never replies.**
`GET /health` first. Then Render logs: a 401 on `/webhooks/linq` means
`LINQ_WEBHOOK_SECRET` does not match the Linq dashboard; a 503 means it is unset.
`python scripts/linq_chats_diag.py` shows whether a chat with that number exists at
all. Linq refuses links in the *first* outbound message of a new chat, so the human
must text first — never open a thread with the pay link.

**Payment link never arrives.**
`python scripts/make_test_payment_request.py`, then
`python scripts/send_payment_to_borrower.py` sends an intro text plus the checkout
URL. The checkout URL also opens in Safari on any phone — Apple Pay is not required.

**They paid but the loan is still `awaiting_deposit`.**
Open `/loans/<id>`. Blank `stripe_payment_intent_id` is deliberate: without a PI
there is no refund path, so the loan refuses to advance. Grab the `pi_...` from the
Stripe Dashboard, write it onto the row, and redeliver the `payment.succeeded`
webhook from Linq. Do not hand the cable over before this clears.

**`Clerk has to SETTLE this one in Band first.`**
`REQUIRE_CLERK_SETTLE=true` and Band has not posted. Either fix Band, or:

```bash
curl -X POST https://<host>/internal/clerk-settle \
  -H "X-Internal-Secret: $INTERNAL_SETTLE_SECRET" \
  -H "Content-Type: application/json" \
  -d '{"loan_id":"<loan_id>","event_id":"manual-<loan_id>"}'
```

That refunds and closes the loan directly. Ship-day default is
`REQUIRE_CLERK_SETTLE=false`, where the lender's `SETTLE` text is enough.

**Condition BLOCKED a clean return** (glare, bad angle, tape hidden).
Clerk posts the full URL in the Band room: `Hiring a Terac inspector. Verdict page
https://<host>/disputes/<loan_id>?t=<token>`. Open it, click **Same item, fine**,
then `SETTLE <loan_id>` again. Say out loud that this is the Terac inspector's page
and you are standing in for the worker.

**`Only the lender can SETTLE.`**
You texted from the wrong phone. `SETTLE` is matched against `LENDER_PHONE`.

**`Already refunded re_...`**
Idempotent, not an error. The refund landed. Show it in Stripe.

**Stripe refund errors mid-demo.**
Refund by hand in the Stripe Dashboard for the exact quoted amount and show that
object. Do **not** re-text `SETTLE` afterwards — the loan has no `stripe_refund_id`
yet, so it would create a second refund.

**Band console is dead.**
Fall back to the Render task-run chain plus the dashboard state column. The
delete-test story still holds: point at `settle` refusing without
`clerk_settle_event_id`.

**Everything is on fire.**
Text `CANCEL` from the borrower phone before the deposit clears — the loan goes
`cancelled` and the item returns to `listed`. Restart from step 1.
