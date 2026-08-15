# RigShare

Text a real iMessage number. Borrow a USB-C charger, Lightning cable, HDMI, or dongle. Pay a $100 hold. Bring it back. Get most of it back.

Docs: [PRD](docs/PRD.md) · [Plan](docs/PLAN.md) · [Preflight](docs/PREFLIGHT.md)

## Stack

Linq (iMessage + Agent Pay) · Stripe refunds · Band (Matcher / Condition / Clerk) · Terac (human inspector + catalog survey) · Pioneer (GLiNER2 / GLiGuard / PII) · Superserve (photo VM) · Render (web + Workflows + Postgres)

## Secrets

Copy `.env.example` to `.env`. Never commit `.env` or `agent_config.yaml`.

## Render

`render.yaml` creates **web** (`rigshare`), **worker** (`rigshare-agents`), and **Postgres** (`rigshare-db`). **Workflows are not Blueprintable** — add that service in the Dashboard after the first deploy.

### Connect this repo

1. GitHub repo: [`PeytonLi/RigShare`](https://github.com/PeytonLi/RigShare) (private).
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

1. Linq dashboard → webhook URL `https://<your-service>.onrender.com/webhooks/linq` (that route is not wired yet; do this after the next code drop).
2. Copy the signing secret into `LINQ_WEBHOOK_SECRET`.
3. Dashboard → **New** → **Workflows** (Python). Same repo. Workflows cannot go in `render.yaml`.
