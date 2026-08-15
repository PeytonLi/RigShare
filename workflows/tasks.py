"""Render Workflows tasks. Stubs until loan logic lands.

Entry: repo-root main.py calls app.start(). Dashboard start command stays `python main.py`.
"""

from render_sdk import Workflows

app = Workflows(default_plan="starter", default_timeout=120)


@app.task
def ingest(loan_id: str) -> dict:
    return {"ok": True, "task": "ingest", "loan_id": loan_id}


@app.task
def quoteAndCharge(loan_id: str) -> dict:
    return {"ok": True, "task": "quoteAndCharge", "loan_id": loan_id}


@app.task
def onDepositPaid(loan_id: str) -> dict:
    return {"ok": True, "task": "onDepositPaid", "loan_id": loan_id}


@app.task
def onHandoff(loan_id: str) -> dict:
    return {"ok": True, "task": "onHandoff", "loan_id": loan_id}


@app.task(timeout_seconds=300)
def inspectReturn(loan_id: str) -> dict:
    return {"ok": True, "task": "inspectReturn", "loan_id": loan_id}


@app.task
def settle(loan_id: str) -> dict:
    return {"ok": True, "task": "settle", "loan_id": loan_id}


@app.task
def forfeit(loan_id: str) -> dict:
    return {"ok": True, "task": "forfeit", "loan_id": loan_id}


@app.task
def openDispute(loan_id: str) -> dict:
    return {"ok": True, "task": "openDispute", "loan_id": loan_id}


@app.task
def onTeracSubmission(loan_id: str) -> dict:
    return {"ok": True, "task": "onTeracSubmission", "loan_id": loan_id}
