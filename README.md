# RigShare

Text a real iMessage number. Borrow a USB-C charger, Lightning cable, HDMI, or dongle. Pay a hold around what it costs to replace. Bring it back. Get most of it back.

Docs: [PRD](docs/PRD.md) · [Plan](docs/PLAN.md) · [Preflight](docs/PREFLIGHT.md)

## Stack

Linq (iMessage + Agent Pay) · Stripe refunds · Band (Matcher / Condition / Clerk) · Terac (human inspector + catalog survey) · Pioneer (GLiNER2 / GLiGuard / PII) · Superserve (photo VM) · Render (web + Workflows + Postgres)

## What people text

| Text | Who | Meaning |
|---|---|---|
| `LEND HDMI` + photo | Lender | Start a listing at the SKU price |
| `LEND HDMI $20 for $3` | Lender | Same, but **their own** hold and rental. Cap $80, deposit must exceed rental + fee |
| `YES` | Lender | Confirm the listing. Nothing is borrowable until this |
| `NEED HDMI` / free text | Borrower | Start a loan, get an Apple Pay link |
| `GOT IT` | Both | Handoff done |
| `RETURNING` + photo | Borrower | Start the return |
| `SETTLE <loan_id>` | Lender | Refund (only from `LENDER_PHONE`) |
| `CANCEL` | Either | Abort before the deposit clears |

Laptops, phones, cameras and other expensive gear are refused at listing time — we
hold the deposit, so the cap is what keeps this from being insurance.

## Operating

- **Money:** one refund path, `app/clerk.py::settle_loan`. It enforces the Band and
  Terac gates and books what the lender is owed. Nothing else calls Stripe.
- **Lender payouts** are recorded, not automated: `/loans/<id>` shows *unpaid* when a
  third party listed the item. Venmo them and the row is your ledger.
- **Overdue loans:** point a Render Workflows cron at the `sweepOverdue` task (hourly
  is plenty). It nags the borrower once past `return_by_at` + 2h and asks Clerk to
  decide. It never keeps a deposit on its own.
- **Demo pricing:** `DEMO_MODE=true` lists everything at Linq's $0.50 floor. A
  lender-set price always wins over it, so you can still film a real partial refund.

## Secrets

Copy `.env.example` to `.env`. Never commit `.env` or `agent_config.yaml`.

## Render

`render.yaml` creates **web** (`rigshare`), **worker** (`rigshare-agents`), and **Postgres** (`rigshare-db`). **Workflows are not Blueprintable** — add that service in the Dashboard after the first deploy.

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
