from __future__ import annotations

import os

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["LINQ_API_KEY"] = "test-linq-key"
os.environ["LINQ_FROM_NUMBER"] = "+12134625502"
os.environ["STRIPE_SECRET_KEY"] = "sk_test_dummy"
os.environ["PUBLIC_BASE_URL"] = "https://rigshare.onrender.com"
os.environ["LENDER_PHONE"] = "+14159909839"
os.environ["TEST_BORROWER_PHONE"] = "+17034051525"
os.environ["INTERNAL_SETTLE_SECRET"] = "test-settle"

from tests.helpers import TEST_WEBHOOK_SECRET

os.environ["LINQ_WEBHOOK_SECRET"] = TEST_WEBHOOK_SECRET

import pytest
from sqlalchemy.orm import Session

from app.config import get_settings
from app.linq_client import FakeLinq, set_linq_gateway

get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _fake_linq():
    fake = FakeLinq()
    set_linq_gateway(fake)
    yield fake
    set_linq_gateway(None)


@pytest.fixture
def db() -> Session:
    from app.db import SessionLocal, engine
    from app.models import Base

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client(db: Session):
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as c:
        yield c
