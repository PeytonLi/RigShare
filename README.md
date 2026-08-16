# RigShare

Text a real iMessage number. Borrow a USB-C charger, Lightning cable, HDMI, or dongle. Pay a hold around what it costs to replace. Bring it back. Get most of it back.

Live: [https://rigshare.onrender.com](https://rigshare.onrender.com)

Docs: [PRD](docs/PRD.md) · [Plan](docs/PLAN.md) · [Demo runbook](docs/DEMO.md) · [Spoken script](docs/SCRIPT.md) · [Preflight](docs/PREFLIGHT.md)

---

## Problem

At events, people need a charger, an HDMI, a dongle. Someone in the room has it. Finding that person is Slack noise. Trusting a stranger with your $20 brick is the actual blocker. Venmo after the fact does not stop anyone from walking off.

Apps do not get installed in a hallway. Group chats leak phone numbers. A $100 scare deposit is not a product people will tap. Insurance for laptops is someone else's company.

## Solution

RigShare is the switchboard. Two 1:1 iMessage threads — borrower and lender never see each other. The hold is about replacement cost, not a scare. Steal it and you just bought it. Bring it back and you get most of it back.

There is no app. Three Band agents run the company: **Matcher** picks the item, **Condition** looks at the return photo, **Clerk** is the only one who can refund. If Condition blocks, Clerk hires a Terac inspector. Happy path never waits on a human.

We refuse laptops, phones, cameras, and anything over $80. We hold the deposit, so the cap is what keeps this from being insurance.

---

## How it works

1. **List.** Lender texts `LEND HDMI` with a photo of the taped cable, then `YES`. Nothing is borrowable until that confirm. Counsel refuses banned gear and bad prices.
2. **Ask.** Borrower texts `NEED HDMI` (or "I need an HDMI for the projector"). Pioneer extracts intent; exact commands still work if the model is down.
3. **Match.** Render starts `quoteAndCharge`. Matcher picks a listed item, or times out at 20s and picks anyway. Borrower gets a quote and an Apple Pay link.
4. **Pay.** They tap, Apple Pay, reply `PAID`. Loan will not walk without a Stripe `pi_...` on the row — no payment intent means no refund path.
5. **Handoff.** Optional Find My ping. Both sides text `GOT IT`. Location is decoration. Possession is the texts.
6. **Return.** Borrower texts `RETURNING` with a photo of the orange tape. Superserve resumes the listing VM and runs ImageMagick AE. Condition writes `ALLOW` or `BLOCKED`.
7. **Settle.** On `ALLOW`, Clerk settles immediately. SMS `SETTLE` is not a refund. Stripe writes a `re_...` on the same PaymentIntent. Item goes back to `listed`.

On `BLOCKED`, Clerk hires a Terac inspector. The page is outbound vs return: same/fine, same/damaged, different. A blocked loan stays stuck until that verdict or a lender override.

### What people text

| Text | Who | Meaning |
|---|---|---|
| `LEND HDMI` + photo | Lender | Start a listing at the SKU price |
| `LEND HDMI $20 for $3` | Lender | Their own hold and rental. Cap $80; deposit must exceed rental + fee |
| `YES` | Lender | Confirm the listing. Nothing is borrowable until this |
| `NEED HDMI` / free text | Borrower | Start a loan, get an Apple Pay link |
| `PAID` | Borrower | Unstick the loan if the pay webhook is quiet |
| `GOT IT` | Both | Handoff done. Both sides required |
| `RETURNING` + photo | Borrower | Start the return inspect |
| `SETTLE` | Lender | Not a refund. Clerk has to SETTLE in Band first |
| `CANCEL` | Either | Abort before the deposit clears |

### Money

Linq Agent Pay charges. Linq cannot refund. Refunds are Stripe on the connected account, and only `app/clerk.py::settle_loan` is allowed to call it.

```
refund = deposit − rental − platform fee
```

Default HDMI: **$15 hold / $3 to the lender / $2 RigShare fee / $10 refunded.** The deposit is a liability, not revenue. `DEMO_MODE=true` lists everything at Linq's $0.50 floor so anyone can Apple Pay; a lender-set price always wins over it.

Lender payouts to third parties are recorded, not automated. `/loans/<id>` shows *unpaid*. Venmo them; the row is the ledger.

---

## Architecture

Render is how the company runs, not just where it is hosted. The loan *is* a Workflows chain.

```
iPhone ──Linq──► Web (FastAPI)
                    │  verify, write event, startTask, 200 in <2s
                    ▼
              Workflows
              ingest → quoteAndCharge → onDepositPaid → onHandoff
                    → inspectReturn → settle | forfeit | openDispute
                    │
                    ├── Postgres (source of truth)
                    ├── Worker: Matcher / Condition / Clerk (Band)
                    ├── Pioneer (guard, NER, PII, copy)
                    ├── Superserve (one paused VM per loan)
                    ├── Stripe (refund only from settle)
                    └── Terac (human inspector on BLOCKED)
```

| Service | Role |
|---|---|
| **Web** (`rigshare`) | Linq / Stripe / Band webhooks, dashboard, disputes, health |
| **Workflows** | One task per loan stage. `settle` is the only Stripe path |
| **Worker** (`rigshare-agents`) | Long-running Band agents |
| **Cron** (`rigshare-overdue`) | Hourly `sweepOverdue`. Nags; never keeps a deposit |
| **Postgres** | Loans, items, events |

Webhook handlers do not call Stripe or Superserve. They start a task and return. Workflows do not sleep-until-webhook — each inbound starts the next task. `inspectReturn` has a 300s timeout. `settle` is idempotent on `stripe_refund_id` and refuses without `clerk_settle_event_id`.

### Agents

| Agent | May do | Must not do |
|---|---|---|
| **Matcher** | `pick_item` | Talk money. Chat a SKU without the tool — loan stays `matching` |
| **Condition** | `ALLOW` / `BLOCKED` from photos + ImageMagick AE | Refund. Hire Terac. The metric is evidence, not a decision |
| **Clerk** | SETTLE after ALLOW (or a Terac fine/damaged). `hire_inspector` on BLOCKED. FORFEIT on different-item | Call Stripe itself |
| **Counsel** | Refuse banned gear and prices over $80 | A fourth Band agent. Matcher and Clerk cite it |

Pioneer: GLiGuard on free text only (exact commands never hit the guard). GLiNER2 for intent / item / price. PII redacted before Band. Decoder rewrites copy; templates win if it garbles a dollar.

Superserve: one Firecracker VM per loan. Write outbound photo on list, pause. Resume on return, compare, pause. Kill on close.

### State machine

```
matching → awaiting_deposit → walking → out → returning → inspecting → settling → closed
                ↘ cancelled          ↘ forfeited
                                     inspecting → blocked  (needs Terac or override)
```

Illegal: `walking` without `stripe_payment_intent_id`. `out` without both `GOT IT`s. `settling` without a Clerk event. `closed` without a `re_...` or an explicit forfeit. One item cannot be in two active loans.

---

## What is load-bearing

- **Orange tape.** Without a visible mark, image compare is a coin flip and Condition false-blocks. Product requirement, not a model trick.
- **Delete Band.** `NEED` stays `matching` or return stays `inspecting`. SMS `SETTLE` does not refund.
- **Delete Terac.** A `BLOCKED` loan stays stuck until hire + verdict, or a lender override on `/disputes/<id>`. Happy path never calls Terac.
- **Delete Pioneer.** `NEED HDMI` / `GOT IT` / `RETURNING` still work. Free text may not.
- **Delete Linq.** There is no product. Do not demo with curl.
- **Location is optional.** `GOT IT` is the handoff. Never infer possession from GPS.
- **Overdue sweep** nags past `return_by_at` + 2h and asks Clerk. It never forfeits on its own.

---

## Stack

Linq (iMessage + Agent Pay) · Stripe refunds · Band (Matcher / Condition / Clerk) · Terac (human inspector + catalog survey) · Pioneer (GLiNER2 / GLiGuard / PII) · Superserve (photo VM) · Render (web + Workflows + worker + cron + Postgres)

---

## Secrets

Copy `.env.example` to `.env`. Never commit `.env` or `agent_config.yaml`.

## Render

`render.yaml` creates **web** (`rigshare`), **worker** (`rigshare-agents`), **cron** (`rigshare-overdue`), and **Postgres** (`rigshare-db`). **Workflows are not Blueprintable** — add that service in the Dashboard after the first deploy.

### Connect this repo

1. GitHub repo: [`PeytonLi/RigShare`](https://github.com/PeytonLi/RigShare).
2. In [Render Dashboard](https://dashboard.render.com) → your project → **New** → **Blueprint**.
3. Connect GitHub if prompted, pick **`PeytonLi/RigShare`**, confirm `render.yaml`.
4. Apply. Wait until `rigshare` is live and `/health` returns `{"ok":true}`.

If you already created an empty web service: **Settings → Build & Deploy → Connect repository** → same repo. Set **Build** `pip install -r requirements.txt` and **Start** `uvicorn app.main:app --host 0.0.0.0 --port $PORT`. Still add a **Background Worker** and **Postgres** (or use Blueprint instead of a lone web service).

### Env vars (do this before going live)

Create an **Environment Group** named `rigshare-secrets`. Paste everything from local `.env` **except** `DATABASE_URL`. Attach the group to **web** and **worker**. Then:

- Set `PUBLIC_BASE_URL` to the web URL (`https://rigshare.onrender.com` or whatever Render assigned).
- Leave `DATABASE_URL` to the Blueprint (`fromDatabase`). Do not paste localhost.
- Change `INTERNAL_SETTLE_SECRET` from `change-me`.
- `LINQ_WEBHOOK_SECRET` stays empty until the webhook exists.

### After the web URL exists

1. Linq dashboard → webhook URL `https://rigshare.onrender.com/webhooks/linq?version=2026-02-03`
   Subscribe to at least `message.received` and `payment.succeeded`.
2. Copy the signing secret into `LINQ_WEBHOOK_SECRET` on the env group. Save and deploy web.
3. Dashboard → **New** → **Workflows** (Python). Same repo. Workflows cannot go in `render.yaml`.
   - Build: `pip install -r requirements.txt`
   - Start: `python main.py` (this is the Workflows file at repo root, not FastAPI)
   - Python: `.python-version` pins `3.12.7`. If the service already exists, also set `PYTHON_VERSION=3.12.7` on it so it stops using 3.14.
   - Link `rigshare-secrets` on Workflows the same way as web/worker. Do not put `DATABASE_URL` in the group.
