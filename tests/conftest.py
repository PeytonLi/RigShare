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
os.environ["REQUIRE_CLERK_SETTLE"] = "true"
os.environ["MATCHER_WAIT_SECONDS"] = "0"
os.environ["DEMO_MODE"] = "false"
os.environ["DEFAULT_DEPOSIT_CENTS"] = "2500"
os.environ["DEFAULT_RENTAL_CENTS"] = "500"
os.environ["DEFAULT_PLATFORM_FEE_CENTS"] = "200"
os.environ["DEMO_DEPOSIT_CENTS"] = "800"
os.environ["DEMO_RENTAL_CENTS"] = "200"
os.environ["DEMO_PLATFORM_FEE_CENTS"] = "100"

from tests.helpers import TEST_WEBHOOK_SECRET

os.environ["LINQ_WEBHOOK_SECRET"] = TEST_WEBHOOK_SECRET

import pytest
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.linq_client import FakeLinq, set_linq_gateway

# Tests must depend only on the environment set above. Left alone, Settings also
# reads the developer's real .env, where a value beats monkeypatch.delenv -- so
# filling in RENDER_WORKFLOW_SLUG locally broke a test that had always passed.
Settings.model_config["env_file"] = None
get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    """monkeypatch restores env vars but not the lru_cache built from them, so a
    test that flips REQUIRE_CLERK_SETTLE leaks its Settings into every later test.
    """
    yield
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
