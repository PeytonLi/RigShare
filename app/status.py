"""Live status checks for the dashboard. Parallel, short timeouts, cached.

Never raises into a page render: every check reports pass/warn/fail/skip.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

import httpx

from app.config import get_settings

_TIMEOUT = 8.0
_TTL_SECONDS = 20

LINQ = "https://api.linqapp.com/api/partner/v3"
BAND = "https://app.band.ai/api/v1/agent"
PIONEER = "https://api.pioneer.ai"
SUPERSERVE = "https://api.superserve.ai"
TERAC = "https://terac.com/api/external/v2"


@dataclass
class Status:
    key: str
    status: str  # pass | warn | fail | skip
    detail: str

    @property
    def css(self) -> str:
        return self.status


class _Result:
    __slots__ = ("key", "status", "detail")

    def __init__(self, key: str, status: str, detail: str = "") -> None:
        self.key = key
        self.status = status
        self.detail = detail

    def to_status(self) -> Status:
        return Status(self.key, self.status, self.detail)


def _get(url: str, headers: dict | None = None, timeout: float = _TIMEOUT):
    return httpx.get(url, headers=headers or {}, timeout=timeout, follow_redirects=True)


def _check_render() -> _Result:
    base = get_settings().public_base_url
    if not base:
        return _Result("render", "warn", "PUBLIC_BASE_URL empty")
    try:
        r = _get(f"{base.rstrip('/')}/health")
        return _Result("render", "pass" if r.status_code == 200 else "fail", f"http {r.status_code}")
    except Exception:
        return _Result("render", "fail", "unreachable")


def _check_stripe() -> _Result:
    key = get_settings().stripe_secret_key
    if not key:
        return _Result("stripe", "skip", "no key")
    try:
        r = _get("https://api.stripe.com/v1/account", {"Authorization": f"Bearer {key}"})
        if r.status_code != 200:
            return _Result("stripe", "fail", f"http {r.status_code}")
        acct = r.json()
        return _Result(
            "stripe",
            "pass" if acct.get("charges_enabled") else "fail",
            f"{acct.get('id', '?')} charges={'on' if acct.get('charges_enabled') else 'OFF'}",
        )
    except Exception:
        return _Result("stripe", "fail", "unreachable")


def _check_linq() -> _Result:
    key = get_settings().linq_api_key
    if not key:
        return _Result("linq", "skip", "no key")
    try:
        r = _get(f"{LINQ}/phone_numbers", {"Authorization": f"Bearer {key}"})
        if r.status_code != 200:
            return _Result("linq", "fail", f"http {r.status_code}")
        nums = r.json().get("phone_numbers", [])
        want = get_settings().linq_from_number
        found = any(n.get("phone_number") == want for n in nums)
        return _Result(
            "linq",
            "pass" if found else "warn",
            want if found else f"from {want} not found",
        )
    except Exception:
        return _Result("linq", "fail", "unreachable")


def _check_band() -> _Result:
    key = get_settings().band_matcher_api_key
    want_id = get_settings().band_matcher_agent_id
    if not key:
        return _Result("band", "skip", "no key")
    try:
        r = _get(f"{BAND}/me", {"X-API-Key": key})
        if r.status_code != 200:
            return _Result("band", "fail", f"http {r.status_code}")
        data = r.json().get("data", {})
        ok = data.get("id") == want_id
        return _Result(
            "band",
            "pass" if ok else "warn",
            f"{data.get('handle', '?')}" if ok else "id mismatch",
        )
    except Exception:
        return _Result("band", "fail", "unreachable")


def _check_superserve() -> _Result:
    key = get_settings().superserve_api_key
    if not key:
        return _Result("superserve", "skip", "no key")
    try:
        r = _get(f"{SUPERSERVE}/sandboxes", {"X-API-Key": key})
        return _Result("superserve", "pass" if r.status_code == 200 else "fail", f"http {r.status_code}")
    except Exception:
        return _Result("superserve", "fail", "unreachable")


def _check_terac() -> _Result:
    key = get_settings().terac_api_key
    if not key:
        return _Result("terac", "skip", "no key")
    try:
        r = _get(f"{TERAC}/projects", {"Authorization": f"Bearer {key}"})
        return _Result("terac", "pass" if r.status_code == 200 else "fail", f"http {r.status_code}")
    except Exception:
        return _Result("terac", "fail", "unreachable")


def _check_pioneer() -> _Result:
    key = get_settings().pioneer_api_key
    if not key:
        return _Result("pioneer", "skip", "no key")
    try:
        r = _get(f"{PIONEER}/v1/models", {"Authorization": f"Bearer {key}"})
        return _Result("pioneer", "pass" if r.status_code == 200 else "fail", f"http {r.status_code}")
    except Exception:
        return _Result("pioneer", "fail", "unreachable")


def _check_money() -> _Result:
    """The one that matters: can the Stripe key see/refund what Linq charged?"""
    lk = get_settings().linq_api_key
    sk = get_settings().stripe_secret_key
    if not (lk and sk):
        return _Result("money", "skip", "need Linq + Stripe keys")
    try:
        r = httpx.get(f"{LINQ}/payment_requests", headers={"Authorization": f"Bearer {lk}"}, timeout=_TIMEOUT)
        if r.status_code != 200:
            return _Result("money", "warn", f"linq http {r.status_code}")
        reqs = r.json().get("data", [])
        if not reqs:
            return _Result("money", "warn", "no payment requests yet")
        pi = (reqs[0].get("stripe") or {}).get("payment_intent_id")
        if not pi:
            return _Result("money", "warn", f"latest request not paid ({reqs[0].get('status')})")
        pr = httpx.get(f"https://api.stripe.com/v1/payment_intents/{pi}",
                       headers={"Authorization": f"Bearer {sk}"}, timeout=_TIMEOUT)
        if pr.status_code == 200:
            return _Result("money", "pass", f"refund path live ({pi[:20]}…)")
        return _Result("money", "fail", "PI invisible to Stripe key")
    except Exception:
        return _Result("money", "fail", "check failed")


_CHECKS: dict[str, callable] = {
    "money": _check_money,
    "render": _check_render,
    "stripe": _check_stripe,
    "linq": _check_linq,
    "band": _check_band,
    "superserve": _check_superserve,
    "terac": _check_terac,
    "pioneer": _check_pioneer,
}

_cache: tuple[float, dict[str, Status]] | None = None


def status_all() -> dict[str, Status]:
    global _cache
    now = time.time()
    if _cache and now - _cache[0] < _TTL_SECONDS:
        return _cache[1]
    results: dict[str, Status] = {}
    with ThreadPoolExecutor(max_workers=len(_CHECKS)) as pool:
        futures = {pool.submit(fn): key for key, fn in _CHECKS.items()}
        for future in as_completed(futures):
            key = futures[future]
            try:
                results[key] = future.result().to_status()
            except Exception:
                results[key] = Status(key, "fail", "check errored")
    _cache = (now, results)
    return results


def status_summary(statuses: dict[str, Status]) -> dict[str, int]:
    counts = {"pass": 0, "warn": 0, "fail": 0, "skip": 0}
    for s in statuses.values():
        counts[s.status] = counts.get(s.status, 0) + 1
    return counts
