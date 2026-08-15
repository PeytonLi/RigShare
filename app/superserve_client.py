"""One Firecracker VM per loan (PRD 9).

Listing photo -> create, write /loan/outbound.jpg, install ImageMagick, pause.
Return photo -> activate, write /loan/return.jpg, `compare -metric AE`, pause.
Closed/cancelled -> kill.

The `superserve` PyPI SDK exists (0.8.2) but is not in requirements.txt, so this
is plain httpx against the same REST API the SDK calls, same as linq_client.
Control plane wants X-API-Key; the per-sandbox data plane wants the access
token handed back by create/activate.
"""

from __future__ import annotations

import logging
import os
import re
from urllib.parse import quote

from app.config import get_settings
from app.linq_client import download_media

log = logging.getLogger("rigshare")

API_BASE = os.getenv("SUPERSERVE_BASE_URL", "https://api.superserve.ai")
SANDBOX_BASE = "https://sandbox.superserve.ai"
TEMPLATE_ID = os.getenv("SUPERSERVE_TEMPLATE_ID", "")

# Auto-pause so a hung inspect does not bill forever (PRD 9).
TIMEOUT_SECONDS = 600

# Photos are normalized to 512x512 before compare, so AE is "pixels that differ"
# out of 262144. Same taped item shot twice lands well under half; a water bottle
# lands near everything. Calibration knob -- retune against the real demo photos.
BLOCK_METRIC = int(os.getenv("SUPERSERVE_BLOCK_METRIC", "150000"))

_INSTALL = "command -v compare >/dev/null || (apt-get update && apt-get install -y imagemagick)"
_COMPARE = (
    "convert /loan/outbound.jpg -resize 512x512! /loan/a.png && "
    "convert /loan/return.jpg -resize 512x512! /loan/b.png && "
    "compare -metric AE -fuzz 10% /loan/a.png /loan/b.png /loan/diff.png"
)


class FakeSuperserve:
    def __init__(self, metric: int = 0) -> None:
        self.metric = metric
        self.created: list[tuple[str, bytes]] = []
        self.compared: list[tuple[str, bytes]] = []
        self.killed: list[str] = []

    def create_loan_sandbox(self, loan_id: str, outbound_jpg: bytes) -> str:
        self.created.append((loan_id, outbound_jpg))
        return f"sbx_{loan_id}"

    def compare_return(self, sandbox_id: str, return_jpg: bytes) -> int:
        self.compared.append((sandbox_id, return_jpg))
        return self.metric

    def kill_sandbox(self, sandbox_id: str) -> None:
        self.killed.append(sandbox_id)


_gateway: FakeSuperserve | None = None


def set_superserve_gateway(gateway: FakeSuperserve | None) -> None:
    global _gateway
    _gateway = gateway


def _api(method: str, path: str, json_body: dict | None = None) -> dict:
    import httpx

    response = httpx.request(
        method,
        f"{API_BASE}{path}",
        headers={"X-API-Key": get_settings().superserve_api_key},
        json=json_body,
        timeout=120.0,
    )
    response.raise_for_status()
    return response.json() if response.content else {}


def _write(sandbox_id: str, token: str, path: str, content: bytes) -> None:
    import httpx

    response = httpx.post(
        f"{SANDBOX_BASE}/files?path={quote(path, safe='')}",
        headers={"X-Access-Token": token, "X-Superserve-Sandbox-Id": sandbox_id},
        content=content,
        timeout=120.0,
    )
    response.raise_for_status()


def _run(sandbox_id: str, token: str, command: str) -> dict:
    import httpx

    response = httpx.post(
        f"{SANDBOX_BASE}/exec",
        headers={"X-Access-Token": token, "X-Superserve-Sandbox-Id": sandbox_id},
        json={"command": command, "timeout_s": 240},
        timeout=300.0,
    )
    response.raise_for_status()
    return response.json()


def _parse_ae(stderr: str) -> int | None:
    """`compare -metric AE` writes the count to stderr, e.g. "144032 (0.549)"."""
    match = re.search(r"\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", stderr)
    return int(float(match.group())) if match else None


def create_loan_sandbox(loan_id: str, outbound_jpg: bytes) -> str | None:
    if _gateway is not None:
        return _gateway.create_loan_sandbox(loan_id, outbound_jpg)
    if not get_settings().superserve_api_key:
        log.info("SUPERSERVE_API_KEY not set; skipping sandbox for loan %s", loan_id)
        return None
    try:
        body: dict = {"name": f"loan-{loan_id}", "timeout_seconds": TIMEOUT_SECONDS}
        if TEMPLATE_ID:
            body["from_template"] = TEMPLATE_ID
        box = _api("POST", "/sandboxes", body)
        sandbox_id, token = str(box["id"]), str(box["access_token"])
        _run(sandbox_id, token, "mkdir -p /loan")
        _write(sandbox_id, token, "/loan/outbound.jpg", outbound_jpg)
        _run(sandbox_id, token, _INSTALL)
        _api("POST", f"/sandboxes/{sandbox_id}/pause")
        return sandbox_id
    except Exception:
        log.exception("Superserve create failed for loan %s", loan_id)
        return None


def compare_return(sandbox_id: str, return_jpg: bytes) -> int | None:
    if _gateway is not None:
        return _gateway.compare_return(sandbox_id, return_jpg)
    if not get_settings().superserve_api_key:
        log.info("SUPERSERVE_API_KEY not set; skipping compare for %s", sandbox_id)
        return None
    try:
        # activate resumes a paused sandbox and hands back a fresh token.
        token = str(_api("POST", f"/sandboxes/{sandbox_id}/activate")["access_token"])
        _write(sandbox_id, token, "/loan/return.jpg", return_jpg)
        # compare exits 1 whenever the images differ, so ignore exit_code.
        metric = _parse_ae(_run(sandbox_id, token, _COMPARE).get("stderr", ""))
        _api("POST", f"/sandboxes/{sandbox_id}/pause")
        return metric
    except Exception:
        log.exception("Superserve compare failed for sandbox %s", sandbox_id)
        return None


def kill_sandbox(sandbox_id: str) -> None:
    if _gateway is not None:
        _gateway.kill_sandbox(sandbox_id)
        return
    if not get_settings().superserve_api_key:
        return
    try:
        _api("DELETE", f"/sandboxes/{sandbox_id}")
    except Exception:
        log.exception("Superserve kill failed for sandbox %s", sandbox_id)


def is_blocked(metric: int | None) -> bool:
    """Metric huge => wrong object => BLOCKED. Unknown metric is not a block:
    no sandbox must not silently forfeit a deposit, Condition/lender decides.
    """
    return metric is not None and metric >= BLOCK_METRIC


def inspect_outbound(loan_id: str, media_id: str | None) -> str | None:
    """Listing photo -> sandbox id for Loan.sandbox_id."""
    if not media_id:
        return None
    return create_loan_sandbox(loan_id, download_media(media_id))


def inspect_return(sandbox_id: str | None, media_id: str | None) -> int | None:
    """Return photo -> AE metric for Loan.compare_metric."""
    if not sandbox_id or not media_id:
        return None
    return compare_return(sandbox_id, download_media(media_id))
