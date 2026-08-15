from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy.orm import Session

from app.agent_api import apply_condition_verdict
from app.counsel import review_listing
from app.models import DeskEvent, SurveyResponse
from app.product import apply_votes, borrower_quote, live_reply, matcher_brief


def _isolate_product(tmp_path: Path, monkeypatch) -> None:
    from app import catalog, product

    monkeypatch.setattr(product, "_STATE_PATH", tmp_path / "product_state.json")
    monkeypatch.setattr(catalog, "WEIGHTS_PATH", tmp_path / "catalog_weights.json")


def test_survey_get_and_post(client, db: Session) -> None:
    page = client.get("/survey")
    assert page.status_code == 200
    assert "You forgot a cable" in page.text

    missing = client.post("/survey", data={"pitch": "a"})
    assert missing.status_code == 400

    thanks = client.post(
        "/survey",
        data={"catalog": ["HDMI", "USB-C charger"], "pitch": "b", "fee": "fair"},
    )
    assert thanks.status_code == 200
    assert "Recorded" in thanks.text
    rows = db.query(SurveyResponse).all()
    assert len(rows) == 1
    assert json.loads(rows[0].catalog_json) == ["HDMI", "USB-C charger"]
    assert rows[0].pitch == "b"


def test_survey_redirects_to_terac_callback(client, db: Session) -> None:
    response = client.post(
        "/survey?teracSubmissionId=sub_1&taskId=task_9",
        data={
            "catalog": ["Lightning"],
            "pitch": "a",
            "fee": "greedy",
            "submission_id": "sub_1",
            "task_id": "task_9",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "terac.com/api/external/callback" in response.headers["location"]
    assert "submissionId=sub_1" in response.headers["location"]
    assert db.query(SurveyResponse).one().terac_submission_id == "sub_1"


def test_counsel_refuses_macbook_and_over_cap() -> None:
    banned = review_listing("lend my macbook", None)
    assert banned.allowed is False
    assert "cheap gear people forget" in banned.message
    assert banned.message.startswith("Counsel refused:")

    priced = review_listing("hdmi", "hdmi", deposit_cents=20_000)
    assert priced.allowed is False
    assert "cap" in priced.message
    assert priced.message.startswith("Counsel refused:")


def test_apply_votes_reorders_sku_and_pitch(db: Session, tmp_path: Path, monkeypatch) -> None:
    _isolate_product(tmp_path, monkeypatch)
    db.add_all(
        [
            SurveyResponse(
                id="r1",
                catalog_json=json.dumps(["USB-C charger", "Lightning"]),
                pitch="b",
                fee_tone="greedy",
            ),
            SurveyResponse(
                id="r2",
                catalog_json=json.dumps(["USB-C charger"]),
                pitch="b",
                fee_tone="fair",
            ),
            SurveyResponse(
                id="r3",
                catalog_json=json.dumps(["HDMI"]),
                pitch="a",
                fee_tone="greedy",
            ),
        ]
    )
    db.commit()
    state = apply_votes(db)
    assert state.applied is True
    assert state.sku_priority[0] == "usbc_charger"
    assert state.pitch_variant == "b"
    assert state.fee_tone == "greedy"
    assert "pitch b" in state.growth_detail.lower()
    assert "Apple Pay in this thread" in borrower_quote("hdmi", 2500, 500, 200, 1800)
    assert matcher_brief().startswith("Prefer listed items")
    assert "USB-C charger" in matcher_brief()
    assert "Borrow a taped USB-C" in live_reply()


def test_apply_votes_endpoint(client, db: Session, tmp_path: Path, monkeypatch) -> None:
    _isolate_product(tmp_path, monkeypatch)
    db.add(
        SurveyResponse(
            id="r1",
            catalog_json=json.dumps(["Lightning"]),
            pitch="a",
            fee_tone="confusing",
        )
    )
    db.commit()
    bad = client.post("/internal/apply-votes", headers={"X-Internal-Secret": "wrong"})
    assert bad.status_code == 401
    ok = client.post("/internal/apply-votes", headers={"X-Internal-Secret": "test-settle"})
    assert ok.status_code == 200
    body = ok.json()
    assert body["ok"] is True
    assert body["sku_priority"][0] == "lightning_cable"
    assert body["fee_tone"] == "confusing"
    desks = {row.desk: row.detail for row in db.query(DeskEvent).all()}
    assert "growth" in desks
    assert "product" in desks


def test_condition_allow_copy_and_blocked_desk(db: Session, _fake_linq) -> None:
    from tests.test_agent_api import _inspecting_loan

    loan = _inspecting_loan(db)
    apply_condition_verdict(db, loan.id, "ALLOW", "evt_allow", "tape matches")
    db.commit()
    assert any("Clerk is settling" in text for _, text in _fake_linq.texts)
    assert any("You do not need to reply SETTLE" in text for _, text in _fake_linq.texts)
    ops = [row.detail for row in db.query(DeskEvent).all() if row.desk == "ops"]
    assert any(detail.startswith("ALLOW") for detail in ops)

    blocked = _inspecting_loan(db)
    apply_condition_verdict(db, blocked.id, "BLOCKED", "evt_block", "no tape")
    db.commit()
    ops = [row.detail for row in db.query(DeskEvent).all() if row.desk == "ops"]
    assert any(detail.startswith("BLOCKED") for detail in ops)


def test_home_shows_desks(client) -> None:
    page = client.get("/")
    assert page.status_code == 200
    assert "The desks" in page.text
    assert "Counsel" in page.text
