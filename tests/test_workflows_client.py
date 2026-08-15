from __future__ import annotations

import pytest

from app.config import get_settings
from app.workflows_client import set_task_starter, start_loan_tasks, start_task


@pytest.fixture(autouse=True)
def _reset_task_starter():
    set_task_starter(None)
    yield
    set_task_starter(None)


def test_empty_slug_returns_none_without_calling_starter(monkeypatch):
    monkeypatch.delenv("RENDER_WORKFLOW_SLUG", raising=False)
    get_settings.cache_clear()

    called = False

    def starter(identifier: str, payload: dict) -> str:
        nonlocal called
        called = True
        return "run-1"

    set_task_starter(starter)
    assert start_task("ingest", "loan-1") is None
    assert called is False


def test_start_task_uses_slug_prefix(monkeypatch):
    monkeypatch.setenv("RENDER_WORKFLOW_SLUG", "rigshare-wf")
    get_settings.cache_clear()

    recorded: list[tuple[str, dict]] = []

    def starter(identifier: str, payload: dict) -> str:
        recorded.append((identifier, payload))
        return "run-1"

    set_task_starter(starter)
    assert start_task("ingest", "loan-42") == "started"
    assert recorded == [("rigshare-wf/ingest", {"loan_id": "loan-42"})]


def test_start_task_returns_none_when_starter_raises(monkeypatch):
    monkeypatch.setenv("RENDER_WORKFLOW_SLUG", "rigshare-wf")
    get_settings.cache_clear()

    def starter(identifier: str, payload: dict) -> str:
        raise RuntimeError("render unavailable")

    set_task_starter(starter)
    assert start_task("ingest", "loan-1") is None


def test_start_loan_tasks_payment_succeeded_calls_on_deposit_paid(monkeypatch):
    monkeypatch.setenv("RENDER_WORKFLOW_SLUG", "rigshare-wf")
    get_settings.cache_clear()

    recorded: list[str] = []

    def starter(identifier: str, payload: dict) -> str:
        recorded.append(identifier)
        return "run-deposit"

    set_task_starter(starter)
    start_loan_tasks("payment.succeeded", "loan-99")
    assert recorded == ["rigshare-wf/onDepositPaid"]
