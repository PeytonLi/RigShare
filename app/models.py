from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class ProcessedEvent(Base):
    __tablename__ = "processed_events"

    event_id: Mapped[str] = mapped_column(String, primary_key=True)
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: uuid.uuid4().hex)
    phone: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Item(Base):
    __tablename__ = "items"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    sku: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, default="", nullable=False)
    lender_user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    status: Mapped[str] = mapped_column(String, default="listed", nullable=False)
    deposit_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    rental_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    platform_fee_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    outbound_media_id: Mapped[str | None] = mapped_column(String, nullable=True)
    # Where the lender listed from, so we can text them before they speak again.
    lender_chat_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Loan(Base):
    __tablename__ = "loans"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    item_id: Mapped[str] = mapped_column(String, ForeignKey("items.id"), nullable=False)
    borrower_user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    lender_user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    state: Mapped[str] = mapped_column(String, default="matching", nullable=False)
    borrower_chat_id: Mapped[str | None] = mapped_column(String, nullable=True)
    lender_chat_id: Mapped[str | None] = mapped_column(String, nullable=True)
    deposit_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    rental_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    platform_fee_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    linq_payment_request_id: Mapped[str | None] = mapped_column(String, nullable=True)
    stripe_payment_intent_id: Mapped[str | None] = mapped_column(String, nullable=True)
    stripe_refund_id: Mapped[str | None] = mapped_column(String, nullable=True)
    clerk_settle_event_id: Mapped[str | None] = mapped_column(String, nullable=True)
    band_room_id: Mapped[str | None] = mapped_column(String, nullable=True)
    sandbox_id: Mapped[str | None] = mapped_column(String, nullable=True)
    compare_metric: Mapped[int | None] = mapped_column(Integer, nullable=True)
    terac_opportunity_id: Mapped[str | None] = mapped_column(String, nullable=True)
    terac_verdict: Mapped[str | None] = mapped_column(String, nullable=True)
    terac_submission_id: Mapped[str | None] = mapped_column(String, nullable=True)
    dispute_token: Mapped[str | None] = mapped_column(String, nullable=True)
    return_media_id: Mapped[str | None] = mapped_column(String, nullable=True)
    manual_refund_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    borrower_got_it_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lender_got_it_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    return_by_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    forfeited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


def get_or_create_user(session: Session, phone: str) -> User:
    user = session.execute(select(User).where(User.phone == phone)).scalar_one_or_none()
    if user is not None:
        return user
    user = User(phone=phone)
    session.add(user)
    session.flush()
    return user


def record_event(
    session: Session, event_id: str, event_type: str, payload: dict
) -> tuple[ProcessedEvent, bool]:
    existing = session.execute(
        select(ProcessedEvent).where(ProcessedEvent.event_id == event_id)
    ).scalar_one_or_none()
    if existing is not None:
        return existing, False
    event = ProcessedEvent(
        event_id=event_id,
        event_type=event_type,
        payload_json=json.dumps(payload),
    )
    session.add(event)
    session.flush()
    return event, True
