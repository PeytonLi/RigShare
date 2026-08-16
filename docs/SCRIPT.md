# RigShare — spoken demo script

Print this. Read the **Say** lines out loud. Do the **Do** lines with your hands.
Exact iMessage copy lives in `app/replies.py` and the hallway runbook in
`docs/DEMO.md`. If a reply does not match, the code changed and this page is stale.

**Time:** ~4 minutes live loop, then 45 seconds of delete-tests if they ask.
**Props:** two iPhones (iMessage, 1:1, never a group), HDMI with orange tape,
laptop with four windows left to right: dashboard `/` · Band `loan-<id>` ·
Stripe Payments · Render Workflows.

`DEMO_MODE` is on so anyone can Apple Pay: **$0.50 hold, $0 rental, $0 fee,
$0.50 refunded.** The real product number is HDMI **$15 hold / $3 to the lender /
$2 RigShare fee / $10 refunded.** Say the real number. Charge the demo number.

---

## 0. Before you walk up (60 s, off camera)

**Do:** Orange tape on the HDMI, visible in both photos. Lender phone texts
`LEND HDMI` with that photo, then `YES`. Dashboard `/` shows one item, status
`listed`. That is the opening shot.

If you skip `YES`, `NEED HDMI` answers "Nothing listed for hdmi yet." That is
the confirmation gate, not a bug.

To film a real partial refund instead of the $0.50 floor:
`LEND HDMI $15 for $3` then `YES`. A lender-set price overrides `DEMO_MODE`.

---

## 1. The problem (25 s)

**Say:**

> At every hackathon and conference, someone needs an HDMI, a USB-C brick, a
> Lightning cable. Someone in the room has it. Finding them is Slack noise.
> Trusting a stranger with your charger is the actual blocker. Venmo after the
> fact does not stop anyone from walking off.
>
> We are not building insurance. We are not holding laptops. RigShare is for
> cheap gear people forget. The hold is about what the thing costs to replace.
> Steal it and you just bought it. Bring it back and you get most of it back.

**Do:** Hold up the taped HDMI. Point at the listed row on the dashboard.

---

## 2. The product (20 s)

**Say:**

> There is no app. You text a real iMessage number. Two 1:1 threads — borrower
> and lender never see each other's number. RigShare is the switchboard.
>
> Three agents run the company. Matcher picks the item. Condition looks at the
> return photo. Clerk is the only one who can refund. If you delete Band, money
> does not move. If Condition blocks, Clerk hires a human inspector on Terac.
> Happy path never waits on a human.

**Do:** Point at the four laptop windows. Do not click yet.

---

## 3. Borrower asks (35 s)

**Do:** Judge's phone texts the Linq number:

```
NEED HDMI
```

Immediate reply: *Looking for a hdmi nearby…*

**Say:**

> That text hit Linq, then Pioneer. GLiGuard checks it is not a jailbreak.
> GLiNER2 pulls intent and item — so "I need an HDMI for the projector" is the
> same as `NEED HDMI`. Commands still work if the model is down. That is why
> the demo cannot die on a parse miss.
>
> Render just started `quoteAndCharge`. Matcher is @mentioned in the Band room
> to pick the item. If Matcher does not pick in 20 seconds, the task times out
> and picks anyway. The borrower is not waiting on an agent to think.

**Do:** Dashboard `/` — loan in `matching`, item still `listed`. Band room
`loan-<id>` — Matcher @mentioned. After pick or timeout: quote, tappable pay
link, then *Pay that link. When it clears, reply PAID.*

**Say:**

> HDMI nearby, marked with orange tape. Fifty-cent hold so you can Apple Pay
> right now. On a real HDMI that is fifteen dollars held, three to the lender,
> two to us, ten refunded. The deposit is a liability, not revenue. We do not
> spend it.

**Do:** `/loans/<id>` Agents — `matcher_item_id`, `matcher_source` (`agent` or
`timeout`). Item is `reserved`, loan `awaiting_deposit`.

---

## 4. Judge pays (45 s)

**Do:** They tap the link, Apple Pay, reply `PAID`. If the webhook is quiet,
`PAID` is what unsticks the loan.

Borrower: *Paid. Meet the lender. When you are holding it, reply GOT IT.*
Lender: *Deposit paid. Hand the item over. When they have it, reply GOT IT.*

Both phones get an iMessage location request. Accepting is optional. Accept on
the lender phone anyway so the other thread gets a maps link.

**Say:**

> Linq charged. Linq cannot refund — that is a Stripe call on our connected
> account, and only one function in the codebase is allowed to make it. The
> payment intent id has to be on the row before the loan can walk. No `pi_`,
> no handoff, no refund path. That is deliberate.
>
> Location is decoration. Find My is wow. `GOT IT` is the handoff. We never
> infer possession from GPS.

**Do:** Stripe → Payments, $0.50 PaymentIntent succeeded. `/loans/<id>` is
`walking` with the `pi_...`. Render shows `onDepositPaid`.

---

## 5. Physical handoff (30 s)

**Do:** Walk the cable across. Both phones text `GOT IT`.

Second person: *You have it. Return by 2 hours. Photo the orange tape and reply RETURNING.*
The other: *Both said GOT IT. Loan is out.*

**Say:**

> Both sides have to say it. One `GOT IT` is not enough. The loan is `out`,
> return clock is running. Overdue sweep nags after two hours of grace. It
> never keeps a deposit on its own — Clerk has to FORFEIT.

**Do:** `/loans/<id>` is `out`, `return_by_at` set. Render shows `onHandoff`.

---

## 6. Return (40 s)

**Do:** Borrower photographs the cable with the tape showing and texts
`RETURNING` with the photo.

*Return photo in. Condition is looking at the orange tape.*

**Say:**

> On listing we opened a Superserve VM, wrote the outbound photo, installed
> ImageMagick, and paused it. Return resumes that same VM, writes the new
> photo, and runs `compare -metric AE`. The orange tape is why this works.
> Without a mark, image compare is a coin flip.
>
> Condition is @mentioned with the metric and a recommended ALLOW or BLOCKED.
> Condition writes the verdict. It does not refund. It does not open Terac.
> If Condition does not write in 20 seconds, inspect applies the ImageMagick
> recommendation itself — same timeout pattern as Matcher.
>
> Happy path is ALLOW. ALLOW never waits on Terac. Clerk settles immediately.
> The lender does not have to text SETTLE. An SMS SETTLE is not a refund.

**Do:** `/loans/<id>` is `inspecting`. Render shows `inspectReturn`. Band room
— Condition @mentioned. On ALLOW the loan goes `returning`, then Clerk posts
`/internal/clerk-settle`.

---

## 7. Settle (50 s)

Lender also gets: *Condition ALLOW. Clerk is settling. You do not need to reply SETTLE.*

If they text `SETTLE` anyway: *Clerk has to SETTLE this one in Band first.*

**Say:**

> Watch Stripe. Same PaymentIntent. Refund object. That is the company.
> Card posting takes five to ten days — show the Refund, not the card.
>
> One refund path. `settle_loan`. It checks Clerk wrote an event id, checks
> the loan is not blocked without a Terac verdict, books what the lender is
> owed, and calls Stripe. Nothing else is allowed to. Kill Band and this
> function refuses. That is the delete test.

**Do:** Stripe → Refund `$0.50`, `re_...`. `/loans/<id>` is `closed` with both
`pi_` and `re_` ids, `clerk_settle_event` filled. Render shows `settle`. Item
back to `listed`.

---

## 8. How the stack is used (say this if they ask, or over the settle)

Do not list vendors like a slide. Point at the window that just moved.

| When it fired | What it did | What it must not do |
|---|---|---|
| **Linq** — every text | Real iMessage number, Agent Pay, pay link, inbound photos, optional location, two 1:1 threads | Refund. Linq cannot. |
| **Pioneer** — every inbound | GLiGuard on free text. GLiNER2 for intent/item/price. PII redacted before Band. Decoder rewrites copy; templates win if it garbles a dollar | Block an exact command. `LEND` / `NEED` / `GOT IT` never reach the guard |
| **Band Matcher** — `NEED` | Picks which listed item fills the request. Tool `pick_item` | Talk money. Skip the tool and chat a SKU — loan stays `matching` |
| **Band Condition** — `RETURNING` | ALLOW or BLOCKED from photos + ImageMagick AE | Refund. Hire Terac. Write `blocked` by chatting |
| **Band Clerk** — after ALLOW or a Terac verdict | Only SETTLE / FORFEIT. Posts our internal API | Call Stripe itself |
| **Superserve** — listing photo, then return | One Firecracker VM per loan. Pause with outbound.jpg. Resume, compare, pause. Kill on close | Decide ALLOW. Metric is evidence |
| **Terac** — Condition BLOCKED, or Saturday catalog | Clerk hires an inspector. Page is outbound vs return, three buttons: same/fine, same/damaged, different. Catalog survey reweighted Matcher | Happy-path ALLOW. Feasibility pricing mid-demo |
| **Render Workflows** — every stage | `ingest → quoteAndCharge → onDepositPaid → onHandoff → inspectReturn → settle` | Refund without `clerk_settle_event_id` |
| **Stripe** — charge via Linq, refund via us | PaymentIntent on pay. Refund object on settle. Idempotent on `re_...` | A second refund if you re-run settle after a manual Dashboard refund |
| **Counsel** — listing time | Refuses laptops, phones, cameras, anything over $80, or a rental that eats the deposit | A fourth Band agent. Matcher and Clerk cite it |

**Agent-run company, in one sentence:**

> There are no employees on the happy path. Three Band agents run matching,
> condition, and money. When they should not decide, Clerk hires a Terac
> inspector. I Venmo a third-party lender later. The dashboard is for me, not
> the customer.

---

## 9. Delete-tests (say out loud, 45 s)

Judges will ask "what if we kill X." Answer before they do.

**Say:**

> Kill Band. `NEED` stays `matching` or return stays `inspecting`. SMS `SETTLE`
> does not refund. The `settle` task refuses without `clerk_settle_event_id`.
>
> Kill Terac. A `BLOCKED` loan stays stuck until Clerk hires an inspector and
> that person — or I standing in for them — taps a verdict, or the lender
> overrides on the dispute page. Happy path never calls Terac, so the hallway
> loop is four minutes either way.
>
> Kill Pioneer. Exact commands still work. Copy falls back to the templates
> you just heard. Free text like "I need an HDMI" may not parse, `NEED HDMI` will.
>
> Kill Superserve. Condition still has to write ALLOW or BLOCKED. Without a
> metric it is more likely to BLOCK, and then we are on the Terac path.
>
> Kill Linq and there is no product. We will not demo with curl.

If they want the blocked path live: hide the tape, `RETURNING`, Condition
`BLOCKED`, Clerk `hire_inspector`, open the URL they posted, click **Same item,
fine**, then Clerk SETTLE. Say you are standing in for the Terac worker.

---

## 10. Close (15 s)

**Say:**

> Stranger's iPhone. Real number. Real Apple Pay. Physical cable. Agents
> matched it, inspected it, and settled it. Stripe shows the refund. The
> deposit came back. The item is listed again.
>
> That is RigShare. Text the number.

**Do:** Dashboard home — item `listed`. Leave Stripe on the Refund object.

---

## If something breaks

Full recovery list is in `docs/DEMO.md`. The three you will actually hit:

1. **No bot reply.** `GET /health`. Render logs: 401 is a Linq webhook secret
   mismatch, 503 means it is unset. The human must text first — Linq refuses
   links in the first outbound of a new chat.
2. **Paid but still `awaiting_deposit`.** Blank `stripe_payment_intent_id` is
   why. Grab `pi_...` from Stripe, write it on the row, redeliver
   `payment.succeeded`. Do not hand the cable over first.
3. **Everything is on fire.** Borrower texts `CANCEL` before the deposit
   clears. Item goes back to `listed`. Restart from `NEED HDMI`.
