from __future__ import annotations

import asyncio
import logging
import os
import threading
from collections.abc import Callable
from typing import Any

from app.config import get_settings

log = logging.getLogger("rigshare")

_starter: Callable[[str, dict[str, str]], Any] | None = None


def set_task_starter(fn: Callable[[str, dict[str, str]], Any] | None) -> None:
    global _starter
    _starter = fn


def _default_starter(identifier: str, payload: dict[str, str]) -> Any:
    import threading

    def _go() -> None:
        async def _run() -> Any:
            from render_sdk import RenderAsync

            return await RenderAsync().workflows.start_task(identifier, payload)

        try:
            asyncio.run(_run())
        except Exception:
            log.exception("Background workflow start failed %s", identifier)

    threading.Thread(target=_go, daemon=True).start()
    return "started"


def _run_local_task(name: str, loan_id: str) -> None:
    from app.db import SessionLocal

    db = SessionLocal()
    try:
        if name == "inspectReturn":
            from app.inspect import run_inspect_return

            run_inspect_return(db, loan_id)
        elif name == "quoteAndCharge":
            from app.inspect import run_quote_and_charge

            run_quote_and_charge(db, loan_id)
        elif name == "openDispute":
            from app.inspect import run_open_dispute

            run_open_dispute(db, loan_id)
        elif name == "forfeit":
            from app.disputes import apply_forfeit
            from app.models import Loan

            loan = db.get(Loan, loan_id)
            if loan is not None:
                apply_forfeit(db, loan)
        db.commit()
    except Exception:
        db.rollback()
        log.exception("Local task %s failed", name)
    finally:
        db.close()


def start_task(name: str, loan_id: str) -> str | None:
    settings = get_settings()
    if not settings.render_workflow_slug:
        if os.environ.get("PYTEST_CURRENT_TEST"):
            log.info("Render workflow slug not configured; skipping task %s", name)
            return None
        threading.Thread(target=_run_local_task, args=(name, loan_id), daemon=True).start()
        return "local"

    identifier = f"{settings.render_workflow_slug}/{name}"
    payload = {"loan_id": loan_id}
    starter = _starter if _starter is not None else _default_starter

    try:
        result = starter(identifier, payload)
    except Exception:
        log.exception("Failed to start workflow task %s", identifier)
        return None

    if result is not None and hasattr(result, "id"):
        return str(result.id)
    return "started"


def start_loan_tasks(event_type: str, loan_id: str | None) -> None:
    if loan_id is None:
        return

    task_name: str | None = None
    if event_type == "message.received":
        task_name = "ingest"
    elif event_type == "payment.succeeded":
        task_name = "onDepositPaid"

    if task_name is not None:
        start_task(task_name, loan_id)
