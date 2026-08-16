"""Pioneer encoder models (PRD 8).

Everything goes through POST /v1/chat/completions with `Authorization: Bearer`.
There is no /inference endpoint -- the earlier version posted there and every
call raised, so the guard always passed and PII was never actually redacted.

Encoder models take a `schema` instead of a prompt and answer with JSON encoded
inside choices[0].message.content:

  entities        {"entities": {"item": [{"text","confidence","start","end"}]}}
  classifications {"data": {"prompt_safety": {"label","confidence"}}}

Only `prompt_safety` is used. GLiGuard's `jailbreak_detection` labels come back
inverted -- "yes" on "GOT IT" and "no" on real injections -- so wiring it up
would block the demo. Also note the classifications schema must be a dict of
task -> labels; the list-of-tasks form answers "safe" for prompts the dict form
scores unsafe at 0.999.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from typing import Any

from app.config import get_settings

log = logging.getLogger("rigshare")

PIONEER_URL = "https://api.pioneer.ai/v1/chat/completions"

NER_ENTITIES = ["intent", "item", "connector", "deposit", "rental_fee"]
PII_ENTITIES = ["person", "email", "phone_number"]

_post: Callable[[str, dict[str, str], dict[str, Any]], dict[str, Any]] | None = None


def set_http(
    fn: Callable[[str, dict[str, str], dict[str, Any]], dict[str, Any]] | None,
) -> None:
    global _post
    _post = fn


def _do_post(
    url: str,
    headers: dict[str, str],
    body: dict[str, Any],
    timeout: float = 20.0,
) -> dict[str, Any]:
    if _post is not None:
        return _post(url, headers, body)
    import httpx

    response = httpx.post(url, headers=headers, json=body, timeout=timeout)
    response.raise_for_status()
    return response.json()


def _call(model: str, schema: dict[str, Any], text: str, api_key: str) -> dict[str, Any] | None:
    """Returns the decoded model payload, or None if the call or parse failed."""
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    body = {"model": model, "messages": [{"role": "user", "content": text}], "schema": schema}
    try:
        envelope = _do_post(PIONEER_URL, headers, body)
        content = envelope["choices"][0]["message"]["content"]
    except Exception:
        log.warning("pioneer call failed model=%s", model, exc_info=True)
        return None
    if isinstance(content, dict):
        return content
    try:
        return json.loads(content)
    except (TypeError, ValueError):
        log.warning("pioneer returned unparseable content model=%s", model)
        return None


def _entities(payload: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    entities = payload.get("entities")
    return entities if isinstance(entities, dict) else {}


def guard_is_safe(text: str) -> bool:
    """False only on a confident `unsafe`. Fails open: a vendor outage must not
    silence the number mid-demo."""
    settings = get_settings()
    key = settings.pioneer_guard_api_key or settings.pioneer_api_key
    if not key:
        return True
    payload = _call(
        settings.pioneer_guard_model_id,
        {"classifications": {"prompt_safety": ["safe", "unsafe"]}},
        text,
        key,
    )
    if payload is None:
        return True
    verdict = (payload.get("data") or {}).get("prompt_safety") or {}
    return str(verdict.get("label", "safe")).lower() != "unsafe"


def extract_entities(text: str) -> dict[str, str]:
    """{entity_label: highest-confidence span}, lowercased for SKU matching."""
    settings = get_settings()
    key = settings.pioneer_ner_api_key or settings.pioneer_api_key
    if not key:
        return {}
    model = settings.pioneer_ner_model_id or settings.pioneer_ner_base_model
    payload = _call(model, {"entities": NER_ENTITIES}, text, key)
    if payload is None:
        return {}
    result: dict[str, str] = {}
    for label, hits in _entities(payload).items():
        if not isinstance(hits, list) or not hits:
            continue
        best = max(hits, key=lambda h: h.get("confidence", 0) if isinstance(h, dict) else 0)
        span = best.get("text") if isinstance(best, dict) else None
        if isinstance(span, str) and span:
            result[label.lower()] = span.lower()
    return result


def redact_pii(text: str) -> str:
    """Blank out person/email/phone before anything reaches Band (PRD 7.3)."""
    settings = get_settings()
    key = settings.pioneer_pii_api_key or settings.pioneer_api_key
    if not key:
        return text
    payload = _call(settings.pioneer_pii_model_id, {"entities": PII_ENTITIES}, text, key)
    if payload is None:
        return text

    spans: list[tuple[int, int]] = []
    for hits in _entities(payload).values():
        if not isinstance(hits, list):
            continue
        for hit in hits:
            if not isinstance(hit, dict):
                continue
            start, end = hit.get("start"), hit.get("end")
            if isinstance(start, int) and isinstance(end, int) and 0 <= start < end <= len(text):
                spans.append((start, end))

    if not spans:
        return text
    # Right to left so earlier offsets stay valid as the string shrinks.
    result = text
    for start, end in sorted(spans, reverse=True):
        result = result[:start] + "[redacted]" + result[end:]
    return result


_DECODER_SYSTEM = (
    "Write one iMessage. No markdown. Keep every dollar amount exactly as given. "
    "One or two short sentences."
)


def compose_reply(
    template_key: str, fallback: str, slots: dict | None = None
) -> tuple[str, str]:
    """Rewrite a canned iMessage via the Pioneer decoder. Never raises.

    Returns `(text, source)` where source is `"decoder"` or `"template"`.
    """
    settings = get_settings()
    if not settings.pioneer_api_key:
        return fallback, "template"

    headers = {
        "Authorization": f"Bearer {settings.pioneer_api_key}",
        "Content-Type": "application/json",
    }
    user_content = (
        f"{template_key}\n{json.dumps(slots or {})}\n{fallback}"
    )
    body: dict[str, Any] = {
        "model": settings.pioneer_decoder_model_id,
        "messages": [
            {"role": "system", "content": _DECODER_SYSTEM},
            {"role": "user", "content": user_content},
        ],
    }
    try:
        envelope = _do_post(PIONEER_URL, headers, body, timeout=8.0)
        content = envelope["choices"][0]["message"]["content"]
    except Exception:
        log.warning("pioneer decoder failed", exc_info=True)
        return fallback, "template"

    if not isinstance(content, str):
        return fallback, "template"
    text = content.strip()
    if not text:
        return fallback, "template"
    if not _money_survived(fallback, text):
        # The prompt says keep amounts exact; this is what happens when it doesn't.
        # A rewritten deposit is a wrong number in a receipt, so ship the template.
        log.warning("decoder altered a dollar amount; using template for %s", template_key)
        return fallback, "template"
    return text, "decoder"


_MONEY = re.compile(r"\$\d+(?:\.\d{2})?")


def _money_survived(fallback: str, rewritten: str) -> bool:
    """Every dollar amount in the template must appear in the rewrite, unchanged."""
    wanted = _MONEY.findall(fallback)
    if not wanted:
        return True
    got = _MONEY.findall(rewritten)
    return all(amount in got for amount in wanted)
