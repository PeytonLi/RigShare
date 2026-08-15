# RigShare — 4-minute hallway demo

Print this. Every text below is copied from `app/loans.py` as it runs today. If a
reply does not match, the code changed and this page is stale.

**Two iPhones.** Lender phone must be the number in `LENDER_PHONE`
(`+14159909839`) — that number lists and confirms. Borrower is any other iPhone,
ideally the judge's. Both text the Linq number in **iMessage**, 1:1, never a group.
Clerk is the only `SETTLE` / `FORFEIT`. An SMS `SETTLE` does not refund.

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
confirmation gate working, not a bug. `YES` is listing confirmation only, not
matching approval. It only ever confirms the sender's own most recent pending
listing.

**To film a real partial refund**, set your own price instead of the demo one:
`LEND HDMI $15 for $3` → $15 hold, $3 to the lender, $2 fee, **$10 refunded**. A
lender-set price overrides `DEMO_MODE`, so nothing else has to change. Over $80, or
a rental that eats the whole deposit, gets refused with the reason in the reply.

---

## 1. Borrower asks (35 s)

Judge's phone → the Linq number:

```
NEED HDMI
```

Immediate reply — no pay link yet:

> Looking for a hdmi nearby…

(`sku` is printed with underscores as spaces, so `NEED HDMI` is `hdmi`.)

**Screen:** dashboard `/` — a loan in `matching`, item still `listed`. Render
starts `quoteAndCharge`. Matcher is @mentioned in Band `loan-<id>` to
`pick_item`. If Matcher does not pick within `matcher_wait_seconds` (default
20), the task times out and picks with `source=timeout`.

After Matcher or timeout reserves the item, two messages go out — the second
is a tappable link:

> hdmi nearby, marked with orange tape. $0.50 hold now. $0 to the lender if you bring it back. $0 RigShare fee. $0.50 refunded.

Prices are $0.50 / $0 / $0 while `DEMO_MODE` is on so anyone can Apple Pay. Set `DEMO_MODE=false` to restore HDMI $15.

**Screen:** `/loans/<id>` Agents — `matcher_item_id`, `matcher_source` (`agent`
or `timeout`), `matched_at`. Item is now `reserved`, loan `awaiting_deposit`.

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

> Return photo in. Condition is looking at the orange tape.

**Screen:** `/loans/<id>` is `inspecting`. Render shows `inspectReturn`. Band
room `loan-<id>` — inspectReturn @mentions Condition with the ImageMagick
metric and a recommended `ALLOW` or `BLOCKED`. It does **not** write `blocked`
and it does **not** open Terac.

Condition's tool writes the verdict: `ALLOW` (loan back to `returning`) or
`BLOCKED`. Happy path (`ALLOW`) never waits on Terac. Clerk `hire_inspector`
is the only `run_open_dispute` caller.

Say this out loud (delete-test):

- Kill Band → NEED stays `matching` or return stays `inspecting`; SMS `SETTLE` does not refund.
- Kill Terac → a `BLOCKED` loan stays stuck until Clerk hire + inspector verdict (or lender override on the dispute page).
- Happy path (`ALLOW`) never waits on Terac.

---

## 5. Settle (50 s)

On Condition `ALLOW`, Clerk settles immediately. The lender gets:

> Condition ALLOW. Clerk is settling. You do not need to reply SETTLE.

Lender phone can still text `SETTLE`. That is not a refund. They get:

> Clerk has to SETTLE this one in Band first.

Settle in the demo is Clerk in Band posting `/internal/clerk-settle` (no
lender yes), or this curl hatch:

```
curl -X POST https://<host>/internal/clerk-settle \
  -H "X-Internal-Secret: $INTERNAL_SETTLE_SECRET" \
  -H "Content-Type: application/json" \
  -d '{"loan_id":"<loan_id>","event_id":"manual-<loan_id>"}'
```

**Screen:** Stripe → the same PaymentIntent → **Refund $0.50**, `re_...`. Then
`/loans/<id>` showing `closed` with both the `pi_` and `re_` ids, Agents
`clerk_settle_event` filled. Render shows `settle`. Card posting takes 5–10
days — show the Refund object, not the card.

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
SMS `SETTLE` never refunds. Clerk is the only SETTLE. Either fix Band so Clerk
can post, or use the curl hatch from section 5. That writes `clerk_settle_event_id`
and refunds. Ship-day default is `REQUIRE_CLERK_SETTLE=true`.

**Condition BLOCKED a clean return** (glare, bad angle, tape hidden).
Clerk `hire_inspector` is the only path that opens Terac. Clerk posts the full
URL in the Band room: `Hiring a Terac inspector. Verdict page
https://<host>/disputes/<loan_id>?t=<token>`. Open it, click **Same item, fine**,
then Clerk SETTLE in Band (or the curl hatch). Say out loud that this is the
Terac inspector's page and you are standing in for the worker. A `BLOCKED` loan
stays stuck until that hire + verdict, or a lender override on the dispute page.

**`Only the lender can SETTLE.`**
You texted `SETTLE` from the wrong phone. The SMS is still not a refund — even
the lender phone only gets the Clerk line.

**`Already refunded re_...`**
Idempotent, not an error. The refund landed. Show it in Stripe.

**Stripe refund errors mid-demo.**
Refund by hand in the Stripe Dashboard for the exact quoted amount and show that
object. Do **not** re-run Clerk SETTLE or the curl hatch afterwards — the loan
has no `stripe_refund_id` yet, so it would create a second refund. SMS `SETTLE`
cannot refund.

**Band console is dead.**
Fall back to the Render task-run chain plus the dashboard state column. NEED
stays `matching` (or times out with `matcher_source=timeout`); return stays
`inspecting` until Condition can write. SMS `SETTLE` still does not refund.
The delete-test story still holds: point at `settle` refusing without
`clerk_settle_event_id`, then the curl hatch.

**Everything is on fire.**
Text `CANCEL` from the borrower phone before the deposit clears — the loan goes
`cancelled` and the item returns to `listed`. Restart from step 1.
