# Preflight: what I need from you before I write product code

I will not start the app until the boxes below are real. "I signed up" is not enough. I need **proof** (a screenshot, a dashboard status, or a value I can call).

Put secrets in `.env` at the repo root (copy `.env.example`). Never paste live keys into chat if you can avoid it. Tell me **PASS/FAIL per section** and any error text.

Work **top to bottom**. Stripe Connect on Linq is the long pole.

---

## 0. Hardware and demo props

- [ ] Two iPhones with iMessage (blue bubbles) to US/reachable numbers
- [ ] Apple Pay set up on the **borrower** phone (the one that will pay)
- [ ] HDMI (or USB-C charger) and **orange tape or a sticky note** on it
- [ ] A laptop for Band + Stripe + Render during judging
- [ ] Your phone number (lender) and a second number (borrower). Write them in `.env` as `LENDER_PHONE` and optionally `TEST_BORROWER_PHONE`

**Need from you:** both numbers in E.164 (`+1...`). Confirm borrower can Apple Pay.

---

## 1. Linq (blocker)

Dashboard: [https://zero.linqapp.com](https://zero.linqapp.com) (confirm login works).

- [ ] Account with a **phone number** assigned to the org
- [ ] API key (Partner / v3). Env: `LINQ_API_KEY`
- [ ] That number in env: `LINQ_FROM_NUMBER` (`+1...`)
- [ ] **Agent Pay → Connect Stripe** completed
- [ ] Stripe status on Linq: **`charges_enabled` = true**. Until this is true, `POST /v3/payment_requests` returns **403**
- [ ] Agent Pay branding: display name **RigShare** (this shows on the pay card)
- [ ] Webhook signing secret once we have a URL (can wait until Phase 1 deploy). Env: `LINQ_WEBHOOK_SECRET`

**You must do:** send yourself a message from the Linq number in their dashboard/sandbox if they have a tester, or be ready to text the number after Phase 1.

**Need from you:**

1. `LINQ_FROM_NUMBER`
2. Confirmation: "Agent Pay charges_enabled: yes/no"
3. If no: what Stripe onboarding step is stuck (identity, bank, etc.)
4. Whether the number is iMessage-capable (Linq capability check is fine; I can run it once I have the key)

**I will not** build a custom iMessage App. We use `link` + optional `agentpay` experience.

Docs: [Payments](https://docs.linqapp.com/guides/payments/), [Connected accounts](https://docs.linqapp.com/guides/payments/connected-accounts/), [Location](https://docs.linqapp.com/guides/location-sharing/)

---

## 2. Stripe (blocker, same account Linq connected)

Linq is merchant-of-record **on this Stripe**. Refunds use **this** secret key.

- [ ] Stripe Dashboard login for the **connected** account
- [ ] Secret key `sk_test_...` or `sk_live_...` — **must match** the mode Linq is charging in. Env: `STRIPE_SECRET_KEY`
- [ ] You can see Payments in the Dashboard after a Linq charge
- [ ] Refunds permission (normal on Standard accounts)

**You must do, in Stripe Dashboard or I do it with the key:**

1. After first Linq $1 payment succeeds, find PaymentIntent `pi_...`
2. Confirm I am allowed to `POST /v1/refunds` on it

**Need from you:** `STRIPE_SECRET_KEY` in `.env`, and "test vs live: ___". If Linq is live charges, test keys will not refund those payments.

**Known gotcha:** Apple Pay App Clip can take ~24 hours after branding. **Link checkout still works.** Always send the `link` part.

---

## 3. Pioneer (blocker for ingest, not for money)

- [ ] API key. Env: `PIONEER_API_KEY`
- [ ] Confirm the catalog includes:
  - `fastino/gliner2-base-v1` (train + infer)
  - `fastino/gliguard-LLMGuardrails-300M`
  - `fastino/gliner2-privacy-filter-PII-multi`
  - at least one decoder (`nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-BF16` or `claude-haiku-5`)
- [ ] Fine-tuning allowed on your plan (LoRA on GLiNER2). If `/felix/training-jobs` is 403, we still ship with base GLiNER2 + entity descriptions

**Need from you:** key in `.env`. Tell me if fine-tune is disabled.

I will run generate + train as soon as the key works. Job id goes in `PIONEER_NER_MODEL_ID`.

Docs: [Fine-tune NER](https://docs.pioneer.ai/guides/fine-tune-ner), [GLiGuard](https://docs.pioneer.ai/concepts/g-li-guard), [GLiNER2-PII](https://docs.pioneer.ai/concepts/g-li-ner-2-pii)

---

## 4. Band (blocker for prize, not for first money demo)

- [ ] Account at [app.band.ai](https://app.band.ai)
- [ ] Three **Connect Remote Agent** registrations (do not name them Assistant/Bot):

| Name | Description to paste |
|---|---|
| Matcher | Picks which listed item should fill a borrow request. Does not talk money. |
| Condition | Compares outbound vs return photos and sandbox metric. May BLOCK a refund. |
| Clerk | Human gate. Posts SETTLE or FORFEIT only after Condition ALLOW and lender yes. |

- [ ] For each: `agent_id` (UUID) and `api_key` (shown once). Env:

```
BAND_MATCHER_AGENT_ID=
BAND_MATCHER_API_KEY=
BAND_CONDITION_AGENT_ID=
BAND_CONDITION_API_KEY=
BAND_CLERK_AGENT_ID=
BAND_CLERK_API_KEY=
```

- [ ] Your user can be added to rooms (you will sit in the loan room as the lender human)
- [ ] Optional fourth agent **Damage** only if extra time

**Need from you:** the six values. Confirm Python 3.11+ on the box that will run agents (Render Worker).

SDK: `band-sdk` extras we will use: start with `[anthropic]` or Pioneer OpenAI-compatible via a small adapter. I will wire Clerk/Matcher to Pioneer/OpenAI-compatible, not five frameworks.

Hacker guide: [band.ai/hacker-guide](https://www.band.ai/hacker-guide)

---

## 5. Superserve (blocker for inspect, not for money)

- [ ] Account + API key. Env: `SUPERSERVE_API_KEY`
- [ ] Permission to create sandboxes, pause, resume, run `apt-get` / ImageMagick
- [ ] Confirm a sandbox can reach the internet to install ImageMagick **or** we use a template that already has it (tell me if you have a template id)

**Need from you:** API key. Template id if any (`SUPERSERVE_TEMPLATE_ID`).

Docs: [Lifecycle](https://docs.superserve.ai/sandbox/lifecycle)

---

## 6. Render (blocker for public webhooks)

- [ ] Account that can create: **Web Service**, **Postgres**, **Workflows** (Workflows are created in the Dashboard, not `render.yaml`)
- [ ] Hackathon credits claimed if they gave a portal
- [ ] GitHub repo this folder can deploy from (this workspace is not a git repo yet). **I need you to `git init` and push** when you want deploy, or grant me permission to init. Say if I should init git.

**Need from you:**

1. Render login working
2. Region preference (Oregon / Virginia / etc.)
3. "You will click Create Workflow in the dashboard when I say so: yes"

I will use `@renderinc/sdk` / Python `render_sdk` Workflows. Web service + Postgres can be Blueprint. Workflows: you click.

Docs: [Workflows](https://render.com/docs/workflows), [Defining tasks](https://render.com/docs/workflows-defining)

---

## 6b. Terac (needed for disputes + catalog survey)

- [ ] Researcher account at [terac.com](https://terac.com)
- [ ] Hackathon credits if they issued them (Slack Terac)
- [ ] API key from org Settings → API Keys. Env: `TERAC_API_KEY`
- [ ] Confirm you can create a project and an unmoderated opportunity

**Need from you:** `TERAC_API_KEY` in `.env` (do not paste in chat). "credits: yes/no"

Docs: [API](https://terac.com/docs/developers/guides), [Tasks](https://terac.com/docs/researchers/opportunities/tasks)

---

## 7. Replay (later, not a blocker)

- [ ] Replay QA account
- [ ] I will give you a public dashboard URL after Phase 8
- [ ] You paste the URL, send me the bug list, I fix, you re-run until clean
- [ ] File false positives for the gift card yourself

Do not wait on Replay to start.

---

## 8. Product decisions I will assume unless you reply

Reply only if you want something else.

| Decision | Default |
|---|---|
| Default deposit | $25.00 charger (`2500`); HDMI $15; hub $30 |
| Default rental to lender | $5.00 charger (`500`); HDMI $3 |
| Default platform fee (borrower-paid) | $2.00 (`200`) |
| Refund | deposit − rental − fee = $18 on charger |
| Demo fallback item | $8 deposit / $2 rental / $1 fee, same code |
| Item cap | Refuse laptop/phone/camera/etc. and stated value > $80 |
| Lender payout | Manual Venmo. DB records amount owed only |
| Status UI | FastAPI HTML dashboard, not iMessage App |
| Decoder | Pioneer Haiku or Nemotron, templates if down |
| Fine-tune | GLiNER2 LoRA only, not Nemotron |

**Need from you if different:** deposit/rental numbers, brand name if not RigShare, whether the Linq number must stay a personal/org name.

---

## 9. What to send me when a section is done

A message like:

```
Linq: PASS, charges_enabled=yes, from=+1..., key in .env
Stripe: PASS, live/test=test, key in .env
Pioneer: PASS, key in .env, fine-tune=yes
Band: PASS, 3 agents in .env
Superserve: PASS, key in .env, template=none
Render: PASS, I can create Workflows
Phones: lender=+1... borrower=+1... Apple Pay=yes
Git: please init / already have GitHub at ...
```

If something FAILs, paste the error body (redact secrets). I will work around or tell you the exact dashboard click.

---

## 10. What I will do first once you say PASS

1. Write `scripts/preflight.py` and run it against your `.env` (health-check every vendor).
2. Only then: Phase 1 webhook skeleton.

If preflight.py FAILs a vendor, we fix that vendor before features. No "we'll mock Linq."
