from __future__ import annotations

import json
import uuid

from sqlalchemy import inspect, select

from app.db import engine
from app.models import Item, Loan, ProcessedEvent, get_or_create_user, record_event


def test_init_db_creates_tables(db) -> None:
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    assert tables == {"processed_events", "users", "items", "loans"}


def test_record_event_idempotent(db) -> None:
    payload = {"foo": "bar"}
    evt1, created1 = record_event(db, "evt-1", "test.event", payload)
    db.commit()
    assert created1 is True

    evt2, created2 = record_event(db, "evt-1", "other.event", {"different": "payload"})
    db.commit()
    assert created2 is False
    assert evt1.event_id == evt2.event_id
    assert json.loads(evt2.payload_json) == payload

    count = db.scalar(select(ProcessedEvent).where(ProcessedEvent.event_id == "evt-1").limit(1))
    assert count is not None
    rows = db.scalars(select(ProcessedEvent)).all()
    assert len(rows) == 1


def test_get_or_create_user_same_phone(db) -> None:
    user1 = get_or_create_user(db, "+15551234567")
    db.commit()
    user2 = get_or_create_user(db, "+15551234567")
    db.commit()

    assert user1.id == user2.id


def test_insert_item_and_loan_with_fks(db) -> None:
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
    )
    db.add(loan)
    db.commit()

    assert loan.item_id == item.id
    assert loan.borrower_user_id == borrower.id
    assert loan.lender_user_id == lender.id
    assert loan.state == "matching"
    assert item.status == "listed"
