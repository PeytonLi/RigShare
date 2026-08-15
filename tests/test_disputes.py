from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.disputes import (
    can_settle_after_dispute,
    dispute_url,
    ensure_dispute_token,
    router,
)
from app.models import Item, Loan, get_or_create_user


def _make_loan(db: Session, *, state: str = "blocked") -> Loan:
    lender = get_or_create_user(db, "+14159909839")
    borrower = get_or_create_user(db, "+17034051525")
    db.flush()

    item = Item(
        id=uuid.uuid4().hex,
        sku="SKU-001",
        title="Test Item",
        lender_user_id=lender.id,
        deposit_cents=2500,
        rental_cents=500,
        platform_fee_cents=200,
        status="out",
        outbound_media_id="media_out",
    )
    db.add(item)
    db.flush()

    loan = Loan(
        id=uuid.uuid4().hex,
        item_id=item.id,
        borrower_user_id=borrower.id,
        lender_user_id=lender.id,
        deposit_cents=2500,
        rental_cents=500,
        platform_fee_cents=200,
        stripe_payment_intent_id="pi_test",
        state=state,
        return_media_id="media_back",
        compare_metric=4200,
    )
    db.add(loan)
    db.commit()
    return loan


@pytest.fixture
def client(db: Session):
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as c:
        yield c


def test_dispute_url_mints_token(db: Session) -> None:
    loan = _make_loan(db)

    url = dispute_url(loan)

    assert loan.dispute_token
    assert url == f"https://rigshare.onrender.com/disputes/{loan.id}?t={loan.dispute_token}"
    assert ensure_dispute_token(loan) == loan.dispute_token  # stable


def test_get_requires_token(client: TestClient, db: Session) -> None:
    loan = _make_loan(db)
    token = ensure_dispute_token(loan)
    db.commit()

    assert client.get(f"/disputes/{loan.id}").status_code == 401
    assert client.get(f"/disputes/{loan.id}?t=nope").status_code == 401

    ok = client.get(f"/disputes/{loan.id}?t={token}")
    assert ok.status_code == 200
    assert "/media/media_out" in ok.text
    assert "/media/media_back" in ok.text
    assert "4200" in ok.text


def test_get_unknown_loan_404(client: TestClient, db: Session) -> None:
    assert client.get("/disputes/nope?t=x").status_code == 404


def test_no_token_on_row_is_not_open_season(client: TestClient, db: Session) -> None:
    loan = _make_loan(db)  # dispute_token never minted

    assert client.get(f"/disputes/{loan.id}?t=").status_code == 401
    assert client.post(f"/disputes/{loan.id}", data={"verdict": "fine"}).status_code == 401


def test_post_bad_token_401(client: TestClient, db: Session) -> None:
    loan = _make_loan(db)
    ensure_dispute_token(loan)
    db.commit()

    response = client.post(f"/disputes/{loan.id}?t=wrong", data={"verdict": "fine"})

    assert response.status_code == 401
    db.refresh(loan)
    assert loan.terac_verdict is None


def _post_verdict(client: TestClient, loan: Loan, verdict: str):
    return client.post(f"/disputes/{loan.id}?t={loan.dispute_token}", data={"verdict": verdict})


def test_verdict_fine(client: TestClient, db: Session) -> None:
    loan = _make_loan(db)
    ensure_dispute_token(loan)
    db.commit()

    assert _post_verdict(client, loan, "fine").status_code == 200

    db.refresh(loan)
    assert loan.terac_verdict == "fine"
    assert loan.manual_refund_cents is None
    assert loan.forfeited_at is None
    assert loan.state == "inspecting"
    assert can_settle_after_dispute(loan) is True


def test_verdict_damaged_sets_lower_manual_refund(client: TestClient, db: Session) -> None:
    loan = _make_loan(db)
    ensure_dispute_token(loan)
    db.commit()

    assert _post_verdict(client, loan, "damaged").status_code == 200

    db.refresh(loan)
    assert loan.terac_verdict == "damaged"
    assert loan.manual_refund_cents == 800  # clean 1800 minus the damage cut
    assert loan.manual_refund_cents < 1800
    assert loan.forfeited_at is None
    assert can_settle_after_dispute(loan) is True


def test_verdict_different_forfeits(client: TestClient, db: Session) -> None:
    loan = _make_loan(db)
    ensure_dispute_token(loan)
    db.commit()

    assert _post_verdict(client, loan, "different").status_code == 200

    db.refresh(loan)
    assert loan.terac_verdict == "different"
    assert loan.forfeited_at is not None
    assert loan.state == "forfeited"
    assert loan.stripe_refund_id is None  # the page never touches Stripe
    assert can_settle_after_dispute(loan) is False


def test_junk_verdict_400(client: TestClient, db: Session) -> None:
    loan = _make_loan(db)
    ensure_dispute_token(loan)
    db.commit()

    assert _post_verdict(client, loan, "sure whatever").status_code == 400
    db.refresh(loan)
    assert loan.terac_verdict is None


def test_blocked_loan_is_not_settleable_without_a_human(db: Session) -> None:
    """PRD 7.5 delete test. Take Terac out and disputed returns stay stuck."""
    loan = _make_loan(db)

    assert can_settle_after_dispute(loan) is False

    loan.terac_submission_id = "sub_1"
    assert can_settle_after_dispute(loan) is True


def test_lender_override_unsticks_a_blocked_loan(db: Session) -> None:
    loan = _make_loan(db)
    assert can_settle_after_dispute(loan) is False

    loan.manual_refund_cents = 1200  # explicit lender override, no Terac involved

    assert can_settle_after_dispute(loan) is True


def test_happy_path_loan_never_needs_terac(db: Session) -> None:
    loan = _make_loan(db, state="inspecting")

    assert can_settle_after_dispute(loan) is True
