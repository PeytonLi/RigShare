"""Render Workflows tasks. Each loan stage is a task judges can see.

Entry: repo-root main.py calls app.start(). Dashboard start command stays `python main.py`.
`settle` is the only task that talks to Stripe, and only after Clerk wrote
`clerk_settle_event_id`. That is the Band delete test.
"""

from render_sdk import Workflows

app = Workflows(default_plan="starter", default_timeout=120)


def _session():
    from app.db import SessionLocal

    return SessionLocal()


@app.task
def ingest(loan_id: str) -> dict:
    return {"ok": True, "task": "ingest", "loan_id": loan_id}


@app.task
def quoteAndCharge(loan_id: str) -> dict:
    from app.inspect import run_quote_and_charge

    db = _session()
    try:
        result = run_quote_and_charge(db, loan_id)
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@app.task
def onDepositPaid(loan_id: str) -> dict:
    return {"ok": True, "task": "onDepositPaid", "loan_id": loan_id}


@app.task
def onHandoff(loan_id: str) -> dict:
    return {"ok": True, "task": "onHandoff", "loan_id": loan_id}


@app.task(timeout_seconds=300)
def inspectReturn(loan_id: str) -> dict:
    from app.inspect import run_inspect_return

    db = _session()
    try:
        result = run_inspect_return(db, loan_id)
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@app.task
def settle(loan_id: str) -> dict:
    from app.clerk import apply_clerk_settle
    from app.models import Loan

    db = _session()
    try:
        loan = db.get(Loan, loan_id)
        if loan is None:
            return {"ok": False, "error": "loan not found"}
        if not loan.clerk_settle_event_id:
            return {"ok": False, "error": "clerk_settle_event_id required"}
        if loan.stripe_refund_id:
            return {"ok": True, "refund_id": loan.stripe_refund_id, "note": "already refunded"}
        apply_clerk_settle(db, loan.id, loan.clerk_settle_event_id)
        db.commit()
        if loan.sandbox_id:
            from app.superserve_client import kill_sandbox

            kill_sandbox(loan.sandbox_id)
        return {"ok": True, "refund_id": loan.stripe_refund_id, "loan_id": loan_id}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@app.task
def forfeit(loan_id: str) -> dict:
    from app.disputes import apply_forfeit
    from app.models import Loan

    db = _session()
    try:
        loan = db.get(Loan, loan_id)
        if loan is None:
            return {"ok": False, "error": "loan not found"}
        if loan.stripe_refund_id:
            return {"ok": False, "error": "already refunded"}
        apply_forfeit(db, loan)
        db.commit()
        return {"ok": True, "task": "forfeit", "loan_id": loan_id}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@app.task
def sweepOverdue(loan_id: str = "") -> dict:
    """PRD 4.4: chase loans past return_by_at + grace. Point a Render cron at this.

    It never forfeits on its own -- it nags the borrower once and hands the decision
    to Clerk. Keeping someone's deposit is a human call.
    """
    from datetime import timedelta, timezone

    from app.band_client import post_room_message
    from app.config import get_settings
    from app.models import Loan, utcnow
    from sqlalchemy import select

    from app.linq_client import send_text

    grace = timedelta(hours=2)
    db = _session()
    try:
        now = utcnow()
        overdue = (
            db.execute(
                select(Loan).where(
                    Loan.state == "out",
                    Loan.return_by_at.is_not(None),
                    Loan.overdue_notified_at.is_(None),
                )
            )
            .scalars()
            .all()
        )
        chased = []
        for loan in overdue:
            due = loan.return_by_at
            if due is None:
                continue
            # SQLite hands back naive datetimes even for timezone=True columns.
            if due.tzinfo is None:
                due = due.replace(tzinfo=timezone.utc)
            if now < due + grace:
                continue
            loan.overdue_notified_at = now
            chased.append(loan.id)
            if loan.borrower_chat_id:
                send_text(
                    loan.borrower_chat_id,
                    "Your RigShare loan is past due. Reply RETURNING with a photo of "
                    "the item and the tape. If it does not come back the deposit is kept.",
                )
            if loan.lender_chat_id:
                send_text(loan.lender_chat_id, "Your item is overdue. We pinged the borrower.")
            if loan.band_room_id:
                post_room_message(
                    loan.band_room_id,
                    f"OVERDUE loan_id={loan.id} past return_by_at + 2h. "
                    "Clerk: FORFEIT if it never comes back.",
                    mention_agent_id=get_settings().band_clerk_agent_id or None,
                    mention_handle="Clerk",
                )
        db.commit()
        return {"ok": True, "task": "sweepOverdue", "chased": chased}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@app.task
def openDispute(loan_id: str) -> dict:
    from app.inspect import run_open_dispute

    db = _session()
    try:
        result = run_open_dispute(db, loan_id)
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@app.task
def onTeracSubmission(loan_id: str) -> dict:
    """Poll the dispute opportunity, pay the expert, tell Clerk the verdict."""
    from app.inspect import run_on_terac_submission

    db = _session()
    try:
        result = run_on_terac_submission(db, loan_id)
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
