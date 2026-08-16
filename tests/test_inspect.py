from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.inspect import run_inspect_return, run_open_dispute, run_quote_and_charge
from app.models import Item, Loan, get_or_create_user
from app.superserve_client import BLOCK_METRIC, FakeSuperserve, set_superserve_gateway
from app.terac_client import FakeTerac, set_terac_gateway


def _loan(db: Session, *, state: str = "returning", outbound: str | None = "m_out", ret: str | None = "m_back") -> Loan:
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
        outbound_media_id=outbound,
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
        return_media_id=ret,
    )
    db.add_all([item, loan])
    db.commit()
    return loan


def test_inspect_allow_small_metric(db: Session, _fake_linq) -> None:
    loan = _loan(db)
    fake = FakeSuperserve(metric=100)
    set_superserve_gateway(fake)
    try:
        result = run_inspect_return(db, loan.id)
        db.commit()
    finally:
        set_superserve_gateway(None)

    assert result["blocked"] is False
    assert result["recommended"] == "ALLOW"
    db.refresh(loan)
    assert loan.state == "inspecting"
    assert loan.compare_metric == 100
    assert loan.sandbox_id == f"sbx_{loan.id}"
    assert loan.terac_opportunity_id is None
    assert not any("SETTLE" in text for _, text in _fake_linq.texts)


def test_inspect_blocks_huge_metric(db: Session, _fake_linq) -> None:
    loan = _loan(db)
    fake = FakeSuperserve(metric=BLOCK_METRIC + 1)
    set_superserve_gateway(fake)
    terac = FakeTerac()
    set_terac_gateway(terac)
    try:
        result = run_inspect_return(db, loan.id)
        db.commit()
    finally:
        set_superserve_gateway(None)
        set_terac_gateway(None)

    assert result["blocked"] is False
    assert result["recommended"] == "BLOCKED"
    db.refresh(loan)
    assert loan.state == "inspecting"
    assert loan.compare_metric == BLOCK_METRIC + 1
    assert loan.terac_opportunity_id is None
    assert not any("doesn't match" in text for _, text in _fake_linq.texts)


def test_inspect_posts_signed_photo_urls(db: Session, _fake_linq, monkeypatch) -> None:
    from app.media import media_url

    loan = _loan(db)
    loan.band_room_id = "room_inspect"
    db.commit()
    posted: list[str] = []
    monkeypatch.setattr(
        "app.inspect.post_room_message",
        lambda room_id, text, **kwargs: posted.append(text),
    )
    fake = FakeSuperserve(metric=100)
    set_superserve_gateway(fake)
    try:
        run_inspect_return(db, loan.id)
        db.commit()
    finally:
        set_superserve_gateway(None)

    assert posted
    assert media_url("m_out") in posted[0]
    assert media_url("m_back") in posted[0]


def test_inspect_skips_without_sandbox(db: Session) -> None:
    loan = _loan(db, outbound=None, ret=None)
    set_superserve_gateway(None)
    result = run_inspect_return(db, loan.id)
    db.commit()
    assert result["blocked"] is False
    assert result["recommended"] == "ALLOW"
    db.refresh(loan)
    assert loan.state == "inspecting"
    assert loan.compare_metric is None


def test_quote_and_charge_records_room_when_band_http_injected(
    db: Session, monkeypatch
) -> None:
    from app.config import get_settings
    from app import band_client

    monkeypatch.setenv("BAND_HUMAN_API_KEY", "human-key")
    monkeypatch.setenv("BAND_MATCHER_AGENT_ID", "agt_matcher")
    monkeypatch.setenv("BAND_CONDITION_AGENT_ID", "agt_condition")
    monkeypatch.setenv("BAND_CLERK_AGENT_ID", "agt_clerk")
    get_settings.cache_clear()
    loan = _loan(db, state="awaiting_deposit")
    calls: list[tuple[str, str]] = []

    def fake_http(method: str, path: str, headers: dict, body: dict | None) -> dict:
        calls.append((method, path))
        if method == "POST" and path == "/me/chats":
            return {"data": {"id": "room_loan"}}
        return {"data": {"id": "ok"}}

    band_client.set_http(fake_http)
    try:
        result = run_quote_and_charge(db, loan.id)
        db.commit()
    finally:
        band_client.set_http(None)
        get_settings.cache_clear()

    assert result["ok"] is True
    db.refresh(loan)
    assert loan.band_room_id == "room_loan"
    assert any(path == "/me/chats" for _, path in calls)


def test_open_dispute_sets_token_without_terac_key(db: Session) -> None:
    loan = _loan(db, state="blocked")
    result = run_open_dispute(db, loan.id)
    db.commit()
    db.refresh(loan)
    assert loan.dispute_token
    assert result["url"].endswith(f"/disputes/{loan.id}?t={loan.dispute_token}")
    assert loan.terac_opportunity_id is None
