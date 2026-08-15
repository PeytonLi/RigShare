"""Generate borrow-SMS NER examples and start a GLiNER2 LoRA job.

    python scripts/pioneer_finetune.py

Does not block the product. If this 403s, we keep base GLiNER2.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import get_settings

PIONEER = "https://api.pioneer.ai"
DATASET = "rigshare-borrow-sms"
LABELS = ["intent", "item", "brand", "connector", "duration", "rental_fee"]


def _headers(key: str) -> dict[str, str]:
    return {"X-API-Key": key, "Content-Type": "application/json"}


def _post(path: str, key: str, payload: dict) -> dict:
    req = urllib.request.Request(
        f"{PIONEER}{path}",
        data=json.dumps(payload).encode(),
        headers=_headers(key),
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode())


def _get(path: str, key: str) -> dict:
    req = urllib.request.Request(f"{PIONEER}{path}", headers=_headers(key))
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode())


def main() -> int:
    settings = get_settings()
    key = settings.pioneer_api_key or os.getenv("PIONEER_API_KEY", "")
    if not key:
        print("FAIL PIONEER_API_KEY missing")
        return 1
    print("generate dataset", DATASET)
    try:
        gen = _post(
            "/generate",
            key,
            {
                "task_type": "ner",
                "dataset_name": DATASET,
                "labels": LABELS,
                "num_examples": 200,
                "domain_description": (
                    "Hackathon and conference iMessage texts about borrowing or lending "
                    "USB-C chargers, Lightning cables, HDMI, dongles, and clickers. "
                    "Short SMS. Intent is lend or borrow/need."
                ),
            },
        )
        print("generate", gen)
    except urllib.error.HTTPError as exc:
        print("WARN generate", exc.code, exc.read()[:400])
        return 1
    gen_job_id = gen.get("job_id")
    if not gen_job_id:
        print("FAIL no job_id returned from /generate")
        return 1
    print("wait for dataset to finish generating")
    for _ in range(80):
        time.sleep(15)
        try:
            status = _get(f"/generate/jobs/{gen_job_id}", key)
        except urllib.error.HTTPError as exc:
            print("WARN poll generate", exc.code)
            continue
        print("generate status", status.get("status"))
        if status.get("status") in {"ready", "failed"}:
            if status.get("status") == "failed":
                print("FAIL generation failed", json.dumps(status, indent=2)[:2000])
                return 1
            break
    else:
        print("FAIL generation still not ready after poll; check /generate/jobs/"
              f"{gen_job_id} later")
        return 1
    try:
        ds = _get(f"/felix/datasets/{DATASET}", key)
        print("dataset ready", ds.get("name"), "count=", ds.get("count"), ds.get("status"))
    except urllib.error.HTTPError as exc:
        print("FAIL dataset check", exc.code, exc.read()[:400])
        return 1
    print("start LoRA job")
    try:
        job = _post(
            "/felix/training-jobs",
            key,
            {
                "model_name": "rigshare-gliner2-borrow",
                "base_model": "fastino/gliner2-base-v1",
                "datasets": [{"name": DATASET}],
                "training_type": "lora",
                "nr_epochs": 5,
                "learning_rate": 5e-5,
            },
        )
    except urllib.error.HTTPError as exc:
        print("FAIL training-jobs", exc.code, exc.read()[:400])
        return 1
    job_id = job.get("id")
    print("job", job_id, job.get("status"))
    print("Put this in PIONEER_NER_MODEL_ID when status is complete:")
    print(job_id)
    for _ in range(40):
        time.sleep(15)
        try:
            status = _get(f"/felix/training-jobs/{job_id}", key)
        except urllib.error.HTTPError as exc:
            print("WARN poll", exc.code)
            continue
        print("status", status.get("status"))
        if status.get("status") in {"complete", "failed", "stopped"}:
            print(json.dumps(status, indent=2)[:2000])
            return 0 if status.get("status") == "complete" else 1
    print("still running; poll later")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
