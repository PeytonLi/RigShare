from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.clerk import can_lender_settle
from app.config import get_settings
from app.disputes import (
    DAMAGE_CUT_CENTS,
    apply_verdict,
    can_settle_after_dispute,
    dispute_url,
    ensure_dispute_token,
)
from app.models import Item, Loan, get_or_create_user


def _loan(db: Session, *, state: str = "blocked") -> Loan:
    lender = get_or_create_user(db, "+14159909839")
    borrower = get_or_create_user(db, "+17034051525")
    item = Item(
        id=uuid.uuid4().hex,
        sku="hdmi",
        title="hdmi",
        lender_user_id=lender.id,
        status="out",
        deposit_cents=1500,
        rental_cents=300,
        platform_fee_cents=200,
        outbound_media_id="media_out",
    )
    loan = Loan(
        id=uuid.uuid4().hex,
        item_id=item.id,
        borrower_user_id=borrower.id,
        lender_user_id=lender.id,
        state=state,
        borrower_chat_id="chat_b",
        lender_chat_id="chat_l",
        deposit_cents=1500,
        rental_cents=300,
        platform_fee_cents=200,
        stripe_payment_intent_id="pi_test",
        sandbox_id="sbx_test",
        dispute_token="tok_test",
        return_media_id="media_back",
    )
    db.add_all([item, loan])
    db.commit()
    return loan


def test_verdict_fine_does_not_refund(db: Session) -> None:
    loan = _loan(db)
    apply_verdict(loan, "fine")
    db.commit()
    db.refresh(loan)
    assert loan.terac_verdict == "fine"
    assert loan.state == "inspecting"
    assert loan.stripe_refund_id is None


def test_verdict_damaged_cuts_refund(db: Session) -> None:
    loan = _loan(db)
    apply_verdict(loan, "damaged")
    db.commit()
    db.refresh(loan)
    assert loan.manual_refund_cents == max(0, 1000 - DAMAGE_CUT_CENTS)
    assert loan.state == "inspecting"


def test_verdict_different_forfeits(db: Session) -> None:
    loan = _loan(db)
    apply_verdict(loan, "different")
    db.commit()
    db.refresh(loan)
    assert loan.state == "forfeited"
    assert loan.forfeited_at is not None
    assert loan.stripe_refund_id is None


def test_blocked_cannot_lender_settle_until_verdict(db: Session, monkeypatch) -> None:
    monkeypatch.setenv("REQUIRE_CLERK_SETTLE", "false")
    get_settings.cache_clear()
    loan = _loan(db)
    assert can_lender_settle(loan) is False
    loan.terac_verdict = "fine"
    assert can_lender_settle(loan) is True


def test_blocked_cannot_lender_settle_when_clerk_required(
    db: Session, monkeypatch
) -> None:
    monkeypatch.setenv("REQUIRE_CLERK_SETTLE", "true")
    get_settings.cache_clear()
    loan = _loan(db)
    assert can_lender_settle(loan) is False
    loan.terac_verdict = "fine"
    loan.clerk_settle_event_id = "evt"
    assert can_lender_settle(loan) is True
    get_settings.cache_clear()


def test_dispute_page_requires_token(client, db) -> None:
    loan = _loan(db)
    missing = client.get(f"/disputes/{loan.id}")
    assert missing.status_code == 401
    ok = client.get(f"/disputes/{loan.id}?t=tok_test")
    assert ok.status_code == 200
    assert "/media/media_out" in ok.text
    assert "/media/media_back" in ok.text


def test_dispute_post_fine(client, db) -> None:
    loan = _loan(db)
    response = client.post(
        f"/disputes/{loan.id}?t=tok_test",
        data={"verdict": "fine"},
    )
    assert response.status_code == 200
    db.expire_all()
    loan = db.get(Loan, loan.id)
    assert loan.state == "inspecting"
    assert loan.terac_verdict == "fine"
    assert loan.stripe_refund_id is None


def test_dispute_post_rejects_bad_token(client, db) -> None:
    loan = _loan(db)
    response = client.post(
        f"/disputes/{loan.id}?t=wrong",
        data={"verdict": "fine"},
    )
    assert response.status_code == 401
    db.expire_all()
    loan = db.get(Loan, loan.id)
    assert loan.state == "blocked"


def test_unknown_loan_404(client) -> None:
    assert client.get("/disputes/nope?t=x").status_code == 404


def test_junk_verdict_400(client, db) -> None:
    loan = _loan(db)

    assert client.post(f"/disputes/{loan.id}?t=tok_test", data={"verdict": "lol"}).status_code == 400

    db.expire_all()
    assert db.get(Loan, loan.id).terac_verdict is None


def test_row_without_a_token_is_not_open_season(client, db) -> None:
    loan = _loan(db)
    loan.dispute_token = None
    db.commit()

    assert client.get(f"/disputes/{loan.id}?t=").status_code == 401
    assert client.post(f"/disputes/{loan.id}", data={"verdict": "fine"}).status_code == 401


def test_dispute_url_mints_a_stable_token(db: Session) -> None:
    loan = _loan(db)
    loan.dispute_token = None

    url = dispute_url(loan)

    assert loan.dispute_token
    assert url == f"https://rigshare.onrender.com/disputes/{loan.id}?t={loan.dispute_token}"
    assert ensure_dispute_token(loan) == loan.dispute_token


def test_delete_test_blocked_loan_needs_a_human(db: Session) -> None:
    """PRD 7.5: no Terac submission/verdict and no lender override => stuck."""
    loan = _loan(db)
    assert can_settle_after_dispute(loan) is False

    loan.terac_submission_id = "sub_1"
    assert can_settle_after_dispute(loan) is True


def test_lender_override_unsticks_a_blocked_loan(db: Session) -> None:
    loan = _loan(db)
    loan.manual_refund_cents = 700  # explicit override, no Terac involved

    assert can_settle_after_dispute(loan) is True


def test_forfeited_loan_is_never_settleable(db: Session) -> None:
    loan = _loan(db)
    apply_verdict(loan, "different")

    assert can_settle_after_dispute(loan) is False
    assert can_lender_settle(loan) is False


def test_happy_path_loan_never_needs_terac(db: Session) -> None:
    loan = _loan(db, state="inspecting")

    assert can_settle_after_dispute(loan) is True
