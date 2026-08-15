# RigShare PRD

**Product:** RigShare  
**One-liner:** Text a real iMessage number to borrow a cable, charger, or dongle. Pay a large deposit in the thread. Return the item. Get most of it back. Steal it and you don't.

**Hackathon job:** Real-world demo in a hallway with two iPhones, a bag of marked cables (USB-C charger, Lightning, HDMI, dongle), Apple Pay, and a laptop showing Band + Stripe + Render + a Terac judgment.

**Not in scope for the weekend:** App Store app, custom iMessage App extension, Stripe Connect payouts to lenders, insurance, background checks.

---

## 1. Problem

At events, people need a USB-C charger, a Lightning cable, an HDMI, a dongle. Someone in the room has it. Finding that person is Slack noise. Trusting a stranger with your $20 brick is the actual blocker. Venmo-after-the-fact does not prevent walking off.

RigShare makes the hold the product. $100 up front via Apple Pay in iMessage. On a clean return the borrower gets back deposit minus rental minus a **borrower-paid platform fee**. Default: **$20** to the lender, **$5** to RigShare, **$75** refunded. Every item has **orange tape or a sticky note** so "returned the wrong one" is visible.

Seed inventory this weekend is **your bag**. You are lender #1 (`+14159909839`). Third-party lenders are the same money path with a Venmo payout later.

---

## 2. Who it is for (weekend)

| Role | Who in the demo | Channel |
|---|---|---|
| **Borrower** | Judge or teammate with Apple Pay on iPhone | 1:1 iMessage with the RigShare number |
| **Lender** | You (Peyton, +14159909839), holding marked cables | 1:1 iMessage with the same number, plus a Band room for the return verdict |
| **Operator** | You, laptop | Dashboard + Band console + Stripe Dashboard + Render task runs |

Borrower and lender never share an iMessage group in v1. RigShare is the switchboard. Reason: Linq location request only works in 1:1 iMessage, and we do not leak phone numbers into Band.

---

## 3. Demo contract (this is the product)

If this loop does not work on a stranger's phone, we do not ship a story. We ship a bug.

1. Borrower texts the **real Linq number** from **their** iPhone.
2. They Apple Pay the deposit in the thread (default **$100.00**).
3. Lender walks the physical item across the room. Optional: Find My updates in the borrower's thread.
4. Both reply `GOT IT`.
5. Borrower photos the item on return (orange tape visible).
6. Lender approves in the Band room.
7. Stripe shows a **partial refund** of deposit minus rental minus platform fee. iMessage says so.

Laptop during judging: Band room (Condition ALLOW + Clerk SETTLE) + Render task chain + Stripe payment and refund.

---

## 4. Money (non-negotiable mechanics)

Linq Agent Pay charges. Linq **cannot refund**. Refunds are Stripe API on **your** connected account.

### 4.1 Amounts

Stored per item / env, not hardcoded in copy:

| Field | Default | Meaning |
|---|---|---|
| `deposit_cents` | `10000` ($100.00) | Charged before handoff |
| `rental_cents` | `2000` ($20.00) | Goes to the lender on clean return (owed in DB; Venmo this weekend) |
| `platform_fee_cents` | `500` ($5.00) | RigShare's take. Charged to the **borrower**, not carved out of the lender after Stripe |
| Refund | `deposit − rental − platform_fee` | default **$75.00** (`7500`) |

Invariant (code must enforce):

```
refund_cents = deposit_cents - rental_cents - platform_fee_cents
refund_cents >= 0
rental_cents + platform_fee_cents < deposit_cents
```

Linq `amount` is **integer cents**. Minimum charge is **50 cents**.

Do **not** take a percentage of `rental_cents` this weekend. A 15% cut of $20 is $3, and Stripe on a $100 charge is about $3.20, so you lose money. The $5 platform fee is the company. The $20 is the lender's.

**You are the vendor when the item is yours.** Lender payout is $0 extra. You keep `rental_cents + platform_fee_cents` minus Stripe. Demo HDMI in your bag = this path.

**You are the marketplace when someone else listed.** You still charge/refund the borrower. You owe the lender `rental_cents`. You keep `platform_fee_cents` minus Stripe. Payout is Venmo/Cash App, recorded as `lender_payout_cents` / `lender_paid_at`.

Demo override: env `DEMO_DEPOSIT_CENTS=2000`, `DEMO_RENTAL_CENTS=400`, `DEMO_PLATFORM_FEE_CENTS=100` so a nervous judge can do $20 / $4 / $1 without a code change. The $100 path must still work for teammates on camera.

### 4.2 Ledger

Default clean return ($100 hold):

```
Borrower --$100 Apple Pay--> RigShare Stripe (you are merchant of record)
On SETTLE:                 Stripe partial refund $75 to borrower
Lender owed:               $20  (Venmo if third party; skip if you are the lender)
RigShare keeps:            $5 platform fee
Stripe fee on $100:        ~2.9% + $0.30 ≈ $3.20 (usually not returned on partial refund)
RigShare net:              ~$1.80 if you paid a third-party lender $20
                           ~$21.80 if you are the lender ($20 + $5 − $3.20)
```

iMessage must show three numbers, never "we keep $25":

> **$100 hold.** **$20** to the lender when it comes back. **$5** RigShare fee. **$75** refunded to you.

The $100 is a **liability**, not revenue. Do not spend deposits. Revenue is `platform_fee_cents` plus `rental_cents` only when you are the lender, minus Stripe.

Card refund posting is **not instant** (often 5–10 days). Demo the Stripe Dashboard `Refund` object and the iMessage confirmation. That is enough.

### 4.3 What we store from Linq `payment.succeeded`

These columns are sacred. No settle without them.

- `linq_payment_request_id`
- `stripe_payment_intent_id` (`pi_...` from the webhook `stripe` object)
- `stripe_refund_id` (`re_...` after refund, for idempotency)

### 4.4 Forfeit

If the item is not returned by `return_by_at` + grace (default 2 hours), Clerk can post `FORFEIT`. No refund (or refund 0). iMessage: deposit kept. This is a deterrent, not insurance. HDMI is ~$12. We refuse listings that look like laptops, cameras, phones.

### 4.5 Item value cap

Condition / ingest **blocks** lend intent if GLiNER item is in `{laptop, phone, camera, tablet, headphones, watch}` or the lender says a value over $80. Copy: "RigShare is for cheap gear people forget. Not that."

---

## 4.6 Seed catalog (what you actually bring)

SKUs are rows, not hardcoded iMessage copy. GLiNER `item` + `connector` maps onto `sku`. Mark **every** physical piece with orange tape.

| sku | What they text | Default `rental_cents` | Notes |
|---|---|---|---|
| `usbc_charger` | usb-c charger, gan, anker brick, mac charger | 1500 ($15) | Highest demand. Bring two if you can. |
| `lightning_cable` | lightning, iphone charger cable | 800 ($8) | Still everywhere. |
| `usbc_cable` | usb-c cable, usbc to usbc | 800 ($8) | |
| `hdmi` | hdmi, hdmi 6ft | 1500 ($15) | Projectors. |
| `usbc_hdmi` | usb-c to hdmi, hdmi dongle | 1500 ($15) | |
| `usbc_hub` | dongle, usb-c hub, multiport | 2000 ($20) | |
| `lightning_usbc` | lightning to usb-c | 800 ($8) | |
| `clicker` | clicker, presenter, logitech pointer | 1000 ($10) | Optional. |

Deposit and platform fee stay **$100 / $5** across SKUs unless the demo-fallback item is used. Rental is what changes.

If Terac Saturday survey says "nobody forgets HDMI, everyone needs USB-C bricks," we reorder this table and the Matcher prompt. That is a real before/after, not a slide.

---

## 4.7 You vs marketplace

Weekend: **you are the vendor** (seed bag) and the **operator**. Marketplace fee still appears on every receipt so the company story is honest. Lender payout to yourself is a no-op. If someone else lists, you owe them `rental_cents`.

---

## 5. What the human types (happy path copy)

Do not wait for perfect NLU. Also accept these **exact commands** so the demo cannot die on a parse miss:

| Command (case insensitive) | Who | Meaning |
|---|---|---|
| `LEND` then a photo | Lender | Start a listing (follow-up questions if needed) |
| `NEED USB-C` / `NEED LIGHTNING` / `NEED HDMI` / free text | Borrower | Start a borrow |
| `YES` | Lender | Approve matching this borrower |
| `GOT IT` | Both | Handoff complete |
| `RETURNING` + photo | Borrower | Start return |
| `CANCEL` | Either, before deposit | Abort |

Free text still goes through GLiNER2. Commands are the fallback.

### 5.1 Lender listing

Inbound: photo of HDMI with orange tape, plus `hdmi 6ft, $20`.

Outbound:

> Got it. HDMI 6ft, orange tape. **$100 hold.** You get **$20** when it comes back. Borrower also pays a **$5** RigShare fee (not taken from you).  
> Reply YES to list it. Mark the item so we can tell it apart.

On YES: item `listed`.

### 5.2 Borrower request

Inbound: `need hdmi for projector 2 hrs`.

Outbound (after Matcher):

> USB-C charger nearby, marked with orange tape.  
> **$100 hold** now. **$15** to the lender if you bring it back. **$5** RigShare fee. **$80** refunded.  
> Pay here: [Agent Pay / link card]

Do not hand off until `payment.succeeded`.

### 5.3 Walking

> Share location when iMessage asks (optional, makes the walk visible).  
> Meet the lender. When you are holding the cable, reply **GOT IT**.

Lender gets the inverse.

### 5.4 Out

> You have the HDMI. Return by **3:40pm**. Photo it with the orange tape showing when you bring it back. Reply **RETURNING** and attach the photo.

### 5.5 Settled

> Returned. Lender **$20**. RigShare fee **$5**. Refunded **$75**. It can take a few days to show on the card. You're done.

### 5.6 Blocked (wrong/damaged item)

> Return doesn't match the outbound photo (missing orange tape). Deposit stays held. Lender is looking at it.

Then human + Damage agent. Possible outcomes: SETTLE anyway, partial refund (manual cents), FORFEIT.

---

## 6. State machine

```
matching
   -> awaiting_deposit     (item reserved, payment request sent)
   -> walking              (paid, location requested, waiting GOT IT from both)
   -> out                  (both GOT IT)
   -> returning            (return photo received)
   -> inspecting           (sandbox compare + Band Condition)
   -> settling             (Clerk SETTLE in flight)
   -> closed               (refund written)

   -> blocked              (Condition BLOCKED or ingest refused)
   -> cancelled            (before deposit)
   -> forfeited            (never returned / explicit FORFEIT)
```

**Illegal transitions** (code must reject):

- `walking` without `stripe_payment_intent_id`
- `out` without both parties `got_it_at`
- `settling` without Band Clerk `SETTLE` event id stored
- `closed` without `stripe_refund_id` OR an explicit `forfeit` flag
- Refund amount other than `deposit_cents - rental_cents - platform_fee_cents` unless `manual_refund_cents` set by Clerk

One item cannot be in two active loans. Listing status: `listed | reserved | out | retired`.

---

## 7. Channels and privacy

### 7.1 Linq

- One Linq number. Branding name **RigShare** in Agent Pay settings.
- Two 1:1 chats per loan: `borrower_chat_id`, `lender_chat_id`.
- Check iMessage capability before location request. SMS users can still pay via web checkout on the **link** part. Location is iMessage-only. If they are on SMS, skip location, still do GOT IT.
- Send deposit as:
  1. `link` part with `checkout_url` (opens Apple Pay App Clip or web checkout). **Required.**
  2. Optional second message: `agentpay` experience so the bubble can flip to Paid.
- Status page as a `link` to `https://<host>/loans/<id>` after each major state.
- Media: download attachments, store in the loan's Superserve VM and a public-ish URL or dashboard-authenticated view for the operator.

**Do not** build a custom Messages extension.

### 7.2 Find My / location

- `POST /v3/chats/{chatId}/location/request` on each 1:1 chat after deposit.
- User must accept. Empty `features` until they do.
- Webhook `location.sharing.started` then poll `GET /v3/chats/{chatId}/location` every **2–3 minutes** while `state=walking`. Coordinates `[lng, lat]`.
- Text the other party a maps link. Do **not** infer GOT IT from GPS.
- If they never share, continue. Location is wow, not source of truth.

### 7.3 Band

Three registered agents, three processes, one room per loan `loan-{id}`:

| Agent | May do | Must not do |
|---|---|---|
| **Matcher** | Pick item, post finding | Refund, talk to Linq |
| **Condition** | `ALLOW` or `BLOCKED` with evidence | Refund |
| **Clerk** | After ALLOW + human lender yes, post `SETTLE` or `FORFEIT` | Refund directly. Clerk writes a row / calls our API; **Workflows** `settle` talks to Stripe |

Human lender is in the Band room for return. Borrower is not. Text posted to Band is PII-redacted.

**Delete test:** Stripe refund is only invoked from the `settle` workflow task, which requires `loans.clerk_settle_event_id` set by the Clerk adapter webhook/tool. Removing Band means Clerk never posts SETTLE, so nothing refunds.

Runtime recruit: on BLOCKED, Clerk does **not** invent a fourth Band agent. Clerk hires a **Terac** human inspector (section 7.5). If Terac has no submission in time, Clerk @mentions the human lender (you) as fallback.

Turn on execution event emit so the Band console shows tool calls for judges.

### 7.5 Terac (human labor when the agents should not decide)

[Terac](https://terac.com) is an expert marketplace: you describe a job, they recruit verified people, you pay on approved completion. API base `https://terac.com/api/external/v2`, `Authorization: Bearer`. MCP exists (`https://terac.com/api/mcp`) but **the product path is REST from Clerk / a Workflows task**, not "I asked Cursor to use MCP during the demo."

RigShare has no employees. Band agents run the company. Terac is how they hire a human for one judgment without you sitting in every dispute.

**Load-bearing path (disputed return):**

1. Condition posts `BLOCKED` (tape missing, ImageMagick metric huge, looks damaged).
2. Clerk posts in Band: hiring an inspector. Workflows task `openDispute` creates a Terac **unmoderated** opportunity (or reuses project `RigShare disputes`) with an **Activity** task whose URL is `https://<host>/disputes/<loan_id>?t=<token>`.
3. That page shows outbound photo vs return photo. Three buttons: **Same item, fine** / **Same item, damaged** / **Different item**.
4. Terac tracks completion (external survey/activity redirect). Webhook or poll `GET .../submissions`. Clerk **approves** the submission so the expert is paid from Terac credits.
5. Clerk posts the verdict in the Band room.
   - `fine` → SETTLE as a clean return (refund deposit − rental − fee). ImageMagick false positive.
   - `damaged` → SETTLE with `manual_refund_cents` lower (keep more). Copy says so.
   - `different` → FORFEIT. Deposit kept.

**Delete test:** a BLOCKED loan cannot SETTLE until a Terac submission id **or** an explicit lender override is on the row. Taking Terac out without the override means disputed returns stuck. Happy-path ALLOW loans never call Terac (hallway demo stays 4 minutes).

**Saturday morning path (catalog, measurable before/after):**

Launch a 2-minute Terac **survey** to general-population (hackathon credits, no doctor/lawyer panel): "Which of these have you actually needed to borrow at a hackathon / conference?" HDMI / USB-C charger / Lightning / dongle / clicker / none.

Before: Matcher weights HDMI equal. After: we seed and prompt-weight whatever humans picked. Screenshot the Terac submissions + the inventory table change. This is the Terac-track "human input changed the product" clip.

**Demo honesty:**

- Feasibility pricing on niche expert panels can take ~1 hour. Do **not** wait on that during judging.
- Use **general population**, 1 participant, short survey/activity, cheap.
- Pre-launch the catalog survey Saturday. For a live dispute, either a Terac worker completes in a few minutes **or** you complete the hosted `/disputes` page yourself while showing the opportunity as launched. The URL is still a Terac-sourced task.
- You need a Terac researcher account, credits, and an API key. Slack them if the hackathon issued $250 credit.

Docs: [Getting started](https://terac.com/docs/developers/guides), [Tasks](https://terac.com/docs/researchers/opportunities/tasks), [API keys](https://terac.com/docs/researchers/integrations/api-keys), [MCP](https://terac.com/mcp).

### 7.6 Dashboard (operator + Replay QA)

Public enough to load, operator-simple:

- Home: list of loans and items
- `/loans/:id`: state, both photos, maps of last location if any, payment intent, refund id, Band room id, sandbox id, Terac opportunity id
- `/disputes/:id`: two photos + Same/Damaged/Different. This is the Terac Activity URL. Token in query string.

This is what Replay QA crawls. It is not the customer UI.

---

## 8. Agents and models (Pioneer)

| Call | Model | When |
|---|---|---|
| Safety | `fastino/gliguard-LLMGuardrails-300M` | Every inbound text. `prompt_safety` + `jailbreak_detection`. Unsafe → canned refusal, no tools. |
| PII | `fastino/gliner2-privacy-filter-PII-multi` | Before Band posts. Redact person, email, phone_number. |
| Extract | Fine-tuned `fastino/gliner2-base-v1` job id | Every inbound. Entities: intent, item, brand, connector, duration, rental_fee. |
| Copy | Pioneer serverless decoder (Nemotron Lightning or Claude Haiku 5) | Short iMessage replies from a template-first prompt. If the decoder is down, send templates. |

Fine-tune Saturday morning via Pioneer `/generate` (~200 NER examples, domain: hackathon borrowing SMS) then LoRA. If training is not `deployed` in 20 minutes, ship with **base** GLiNER2 + entity descriptions and keep commands. Do not block the money loop on the fine-tune.

---

## 9. Superserve

One Firecracker VM per **loan**, not per message.

- Create when listing photo arrives. Write `/loan/outbound.jpg`. Install ImageMagick once. `pause()`.
- Resume on return photo. Write `/loan/return.jpg`. `compare -metric AE outbound return diff.png`. Parse the metric. `pause()`.
- `kill()` on closed/cancelled.

Auto-pause `timeoutSeconds=600` so a hung inspect does not bill forever.

**Tape rule:** lenders must mark the item. Without a visible mark, image compare is a coin flip and Condition will false-block. Product requirement, not a model trick.

---

## 10. Render

| Service | Role |
|---|---|
| Web service | Linq + Stripe + Band webhooks, dashboard, health |
| Workflows | `ingest`, `quoteAndCharge`, `onDepositPaid`, `onHandoff`, `inspectReturn`, `settle`, `forfeit` |
| Postgres | Source of truth |
| (optional) Key Value | Webhook idempotency keys if we do not want a table. Prefer a `processed_events` table. |

Webhook handler: verify signature, insert event, `startTask`, return 200 in under 2 seconds. Never call Stripe refund or Superserve from the request thread except health checks.

Workflows do not sleep-until-webhook. Each webhook starts the next task. `inspectReturn` timeout ~300s with retries. `settle` is idempotent on `stripe_refund_id`.

---

## 11. Non-goals (weekend)

- Custom iMessage App / Messages extension
- Group iMessage for the loan
- Stripe Connect accounts / automatic lender payout
- Identity beyond phone number
- Time-based rental math (hourly). Flat `rental_cents` per loan.
- Push notifications outside iMessage
- Replay inside the product. QA only, after dashboard exists.
- Android-first. RCS/SMS can pay via web checkout. Location skipped.

---

## 12. Prize mapping (so we do not forget)

| Prize | How we actually use it |
|---|---|
| Linq | Real number, Agent Pay $100, link card, optional location, inbound photos, two 1:1 threads |
| Band | Matcher finding changes the item; Condition can BLOCK refund; Clerk is the only SETTLE; room per loan |
| Terac | Catalog survey Saturday (inventory before/after). Disputed returns: Clerk hires a human inspector; SETTLE waits on that verdict |
| Superserve | Pause VM with outbound photo; resume to compare return |
| Pioneer | GLiGuard, GLiNER2-PII, fine-tuned GLiNER2, decoder copy |
| Render Workflows | Each loan stage is a task; judges see the chain |
| Agent-run company | Real Apple Pay + real refund on Stripe during the event. No employees: Terac is the hired human |
| Replay | Point at dashboard URL once, fix bugs, clean report. Not a feature. |

---

## 13. Risks (say them out loud)

| Risk | Mitigation |
|---|---|
| Stripe `charges_enabled` false | Connect Friday. $1 test charge to yourself before any feature. |
| App Clip not live for 24h | Always send `link` part. Web checkout works. |
| Judge will not pay $100 | Item-level / env deposit. Teammate still films $100. |
| Linq refund confusion | Never call Linq for refunds. Only Stripe. |
| Location empty | GOT IT is the handoff. Location optional. |
| Band used as a log | Clerk SETTLE is a hard gate in `settle` task. |
| Fine-tune slow | Commands + base GLiNER2 fallback. |
| Image compare useless | Orange tape. Refuse unmarked listings. |
| Terac too slow for hallway | Happy path never calls Terac. Catalog survey Saturday. Dispute URL works even if you tap the buttons. |
| Webhook retries double-refund | Idempotency on payment intent + refund id. |
| You hold stolen-item money | Cap item value. You are not a bank. Copy says so. |

---

## 14. Success

**Must:** one live $ deposit, one live partial refund, physical handoff, Band ALLOW+SETTLE, Render task chain visible.

**Should:** location share during the walk, GLiNER2 fine-tune deployed, Condition BLOCKED on a no-tape photo then ALLOW on taped photo.

**Nice:** second real borrower at the venue paying a smaller deposit for a real dongle.
