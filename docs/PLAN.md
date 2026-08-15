# RigShare build plan (fastest path that still works)

Order is the product. If a later layer is pretty and layer 2 (money) is not live, we are losing.

**Language:** Python 3.12 everywhere. Band's Python SDK is the mature one. Render Workflows, Linq, Pioneer, Stripe, Superserve all speak Python. Dashboard is FastAPI + server-rendered HTML (no React). One deployable.

**Repo layout (when we start coding):**

```
app/
  main.py                 # FastAPI: webhooks + dashboard
  config.py
  db.py                   # SQLAlchemy + Postgres
  models.py
  linq_client.py
  stripe_client.py
  pioneer_client.py
  superserve_client.py
  terac_client.py
  band_bridge.py          # HTTP from Clerk tool -> start settle task
  templates/              # loans list + loan detail + dispute page
workflows/
  tasks.py                # Render Workflows task() defs
agents/
  matcher.py
  condition.py
  clerk.py
scripts/
  preflight.py            # hits every vendor, prints PASS/FAIL
  pioneer_finetune.py     # generate + train GLiNER2
  stripe_refund_selftest.py
  terac_catalog_survey.py # Saturday morning which-cables survey
render.yaml               # web + postgres. Workflows created in Dashboard.
```

---

## Phase 0 — Preflight (YOU, blocking)

Nothing else starts until `scripts/preflight.py` would print all PASS (we will write that script first).

Do the human account work in `docs/PREFLIGHT.md`. Paste secrets into `.env` (never commit).

**Timebox:** this can be 30 minutes or 6 hours depending on Stripe verification. Start it immediately. App Clip activation can take ~24h. Web checkout does not wait.

---

## Phase 1 — Skeleton on Render (45–90 min)

Goal: public HTTPS URL that Linq can webhook.

1. FastAPI `/health` → `{ok: true}`
2. Render Web Service + Postgres
3. `processed_events` + empty `users/items/loans` tables
4. Linq webhook endpoint `/webhooks/linq` that verifies signature (or logs raw if we must debug once), stores event, returns 200
5. Send a test SMS/iMessage to the Linq number, confirm a row in Postgres

**Exit:** you text the number, you see the payload in Render logs and a DB row. The bot can reply a hardcoded `RigShare is live. LEND or NEED.`

If webhooks fail, we are not allowed to "build locally and demo with curl." Linq is the product.

---

## Phase 2 — Money loop (the whole company) (60–90 min)

Goal: $1 (then $100) charge and partial refund **without** borrowing logic.

1. `POST /v3/payment_requests` with `metadata.loan_id=test`
2. Send `checkout_url` as a **link** part to your phone
3. Pay with Apple Pay (or web checkout)
4. Handle `payment.succeeded`, save `stripe.payment_intent_id`
5. Call Stripe `Refunds.create(payment_intent=..., amount=half)`
6. Save `stripe_refund_id`, text "refunded X"

**Exit:** Stripe Dashboard shows a succeeded PaymentIntent and a Refund. iMessage showed the pay card. This is the agent-run-company screenshot.

Do this at **$100** once with a teammate as soon as $1 works. Do not wait until Sunday.

Idempotency: if the same `payment.succeeded` is delivered twice, do not create two refunds in this test script. Same code path as production `settle`.

---

## Phase 3 — State machine + commands (60 min)

No LLM required.

Commands: `LEND`, `NEED USB-C`, `NEED LIGHTNING`, `NEED HDMI`, `YES`, `GOT IT`, `RETURNING`, `CANCEL`.

Two phone numbers in env. Lender is `+14159909839` (you). Borrower is whoever texts NEED.

Flow:

1. LEND + photo → create item, download media to disk/sandbox later (for now store Linq attachment id)
2. NEED HDMI → if a listed HDMI exists, create loan `awaiting_deposit`, run Phase 2 charge at `deposit_cents`
3. On paid → `walking`, ask both for `GOT IT`
4. Both GOT IT → `out`
5. RETURNING + photo → skip inspect, go to **manual** settle for now: operator texts a magic `SETTLE <loan_id>` from lender phone OR dashboard DEV button

**Exit:** full physical HDMI loop with $ deposit and refund, using commands only. This is already a demo. Everything after this is prize depth.

---

## Phase 4 — Pioneer ingest (45 min) + fine-tune in parallel (20 min + wait)

1. Script `pioneer_finetune.py`: `/generate` 200 NER examples, `POST /felix/training-jobs` on `fastino/gliner2-base-v1` LoRA. Poll until `deployed`. Save job id in env `PIONEER_NER_MODEL_ID`.
2. Inbound path: GLiGuard → if unsafe stop → GLiNER2-PII for Band later → NER extract → map to commands (`intent=borrow` + `item=hdmi` ≡ `NEED HDMI`).
3. Decoder optional: if Pioneer generate fails, templates win.

**Exit:** `need an hdmi for the projector` creates the same loan as `NEED HDMI`. Fine-tune can land after Phase 3 is already demoable.

---

## Phase 5 — Superserve inspect (45 min)

1. On listing photo: `Sandbox.create`, write `outbound.jpg`, install ImageMagick, `pause`, save `sandbox_id`
2. On return photo: `connect`, write `return.jpg`, `compare -metric AE`, save metric on loan
3. If metric is huge (wrong object) → state `blocked` and do not auto-settle
4. If small → allow Phase 6 / settle

**Exit:** taped USB-C charger ALLOW; photo of a water bottle BLOCKED.

---

## Phase 6 — Band (90 min)

This is the easiest layer to fake and the one judges will delete-test. Agents already exist in `.env`.

1. One Render Worker running Matcher, Condition, Clerk (`asyncio.gather` three `agent.run()`).
2. `ingest` / Matcher: create room `loan-{id}`, add Matcher+Clerk, post redacted ask, Matcher picks item.
3. `inspectReturn`: @Condition with metric + photo URLs. Condition replies ALLOW or BLOCKED.
4. Clerk: if ALLOW, @human lender. On lender yes, Clerk HTTP POSTs `/internal/clerk-settle`. That `startTask(settle)`.
5. `settle` refuses unless `clerk_settle_event_id` is set.

**Exit:** refund does not happen if you kill Band. Happens when Clerk posts SETTLE. Record a 30s screen capture of the room.

---

## Phase 6b — Terac (45 min, after Band exists)

1. Terac API key in `.env`. Create project `RigShare`.
2. Saturday: `scripts/terac_catalog_survey.py` launches a short survey. Screenshot results. Update Matcher weights / which SKUs you physically bring.
3. `/disputes/{id}` page with two photos + three buttons.
4. On Condition BLOCKED, `openDispute` creates/launches a Terac Activity pointing at that URL.
5. `onTeracSubmission` → Clerk posts verdict → SETTLE or FORFEIT.

**Exit:** no-tape return does not refund until a Terac (or lender override) verdict exists. Catalog survey has at least one real human completion.

Happy path (ALLOW) must still demo without waiting on Terac.

---

## Phase 7 — Location (30 min, skippable)

After deposit: location request both chats. On `location.sharing.started`, poll every 3 minutes while `walking`, send maps link. Stop polling on `out`.

If this slips, demo still works.

## Phase 7 — Location (30 min, skippable)

After deposit: location request both chats. On `location.sharing.started`, poll every 3 minutes while `walking`, send maps link. Stop polling on `out`.

If this slips, demo still works.

---

## Phase 8 — Dashboard + Replay (30 min)

`/`, `/loans`, `/loans/{id}` with photos, state, stripe ids, band room link if we have a URL.

Paste public URL into Replay QA. Fix real bugs. File false positives. Do not rebuild the UI.

---

## Phase 9 — Demo kit (20 min)

- Orange tape on **every** cable: USB-C charger, Lightning, HDMI, dongle
- Two iPhones charged, Apple Pay working, iMessage (not SMS) to the Linq number
- Laptop windows: Band room, Stripe payment, Render task runs, dashboard, Terac opportunity
- Fallback deposit $20 item in DB if judge hesitates
- Script printed in `docs/DEMO.md` (write when Phase 3 works)

---

## Parallelization (you vs me)

| You | Me (once preflight secrets exist) |
|---|---|
| Stripe + Linq Connect, $1 pay test in dashboard | Skeleton, webhooks, DB, workflows |
| Band three agents created, keys copied | Pioneer fine-tune script kicking off |
| Terac researcher account + API key + credits | Terac survey + dispute task |
| Two iPhones, tape, USB-C / Lightning / HDMI | Money loop + commands |
| Render account, Workflows service created in dashboard (not blueprintable) | Agents + sandbox |
| Replay QA after I give you a URL | Copy, location, dashboard |

Render Workflows must be created in the Render Dashboard by a human. I cannot do that from a `render.yaml` Blueprint. You click it. I will give exact steps when we deploy.

---

## Explicit non-work (do not touch)

- Next.js / React
- Shipping an iMessage App
- Stripe Connect marketplace
- Hourly pricing
- Group chats
- Replay SDK in the app
- Fine-tuning Nemotron (GLiNER2 only)

---

## Definition of done

A stranger's iPhone, our Linq number, a real deposit, a physical cable, Band SETTLE, Stripe partial refund, Render showing `ingest → quoteAndCharge → onDepositPaid → onHandoff → inspectReturn → settle`.

That is the whole game.
