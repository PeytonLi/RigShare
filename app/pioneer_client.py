from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.config import get_settings

GUARD_URL = "https://api.pioneer.ai/v1/chat/completions"
INFERENCE_URL = "https://api.pioneer.ai/inference"

_post: Callable[[str, dict[str, str], dict[str, Any]], dict[str, Any]] | None = None


def set_http(
    fn: Callable[[str, dict[str, str], dict[str, Any]], dict[str, Any]] | None,
) -> None:
    global _post
    _post = fn


def _do_post(url: str, headers: dict[str, str], body: dict[str, Any]) -> dict[str, Any]:
    if _post is not None:
        return _post(url, headers, body)
    import httpx

    response = httpx.post(url, headers=headers, json=body, timeout=20.0)
    response.raise_for_status()
    return response.json()


def _classification_map(data: dict[str, Any]) -> dict[str, str]:
    classifications = data.get("classifications")
    if not isinstance(classifications, list):
        return {}
    result: dict[str, str] = {}
    for item in classifications:
        if not isinstance(item, dict):
            continue
        label = item.get("label")
        value = item.get("value")
        if isinstance(label, str) and isinstance(value, str):
            result[label.lower()] = value.lower()
    return result


def guard_is_safe(text: str) -> bool:
    settings = get_settings()
    if not settings.pioneer_api_key:
        return True

    model = settings.pioneer_guard_model_id or "fastino/gliguard-LLMGuardrails-300M"
    body = {
        "model": model,
        "messages": [{"role": "user", "content": text}],
        "schema": {
            "classifications": [
                {
                    "task": "prompt_safety",
                    "labels": ["safe", "unsafe"],
                    "multi_label": False,
                    "threshold": 0.5,
                },
                {
                    "task": "jailbreak_detection",
                    "labels": ["benign", "prompt_injection", "jailbreak_attempt"],
                    "multi_label": True,
                    "threshold": 0.5,
                },
            ]
        },
        "include_confidence": True,
    }
    headers = {
        "Authorization": f"Bearer {settings.pioneer_api_key}",
        "Content-Type": "application/json",
    }

    try:
        data = _do_post(GUARD_URL, headers, body)
    except Exception:
        return True

    labels = _classification_map(data)
    if labels.get("prompt_safety") == "unsafe":
        return False

    jailbreak = labels.get("jailbreak_detection", "")
    if jailbreak and jailbreak not in ("benign", ""):
        return False

    return True


def _first_text(value: Any) -> str | None:
    if isinstance(value, str) and value:
        return value
    if isinstance(value, list) and value:
        first = value[0]
        if isinstance(first, str) and first:
            return first
    return None


def _parse_entities(data: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}

    entities = data.get("entities")
    if isinstance(entities, list):
        for item in entities:
            if not isinstance(item, dict):
                continue
            label = item.get("label")
            text = item.get("text") or item.get("span")
            if isinstance(label, str) and isinstance(text, str) and text:
                key = label.lower()
                if key not in result:
                    result[key] = text.lower()
        return result

    if isinstance(entities, dict):
        for label, value in entities.items():
            if not isinstance(label, str):
                continue
            text = _first_text(value)
            if text:
                key = label.lower()
                if key not in result:
                    result[key] = text.lower()
        return result

    predictions = data.get("predictions")
    if isinstance(predictions, list):
        for item in predictions:
            if not isinstance(item, dict):
                continue
            label = item.get("label")
            text = item.get("span") or item.get("text")
            if isinstance(label, str) and isinstance(text, str) and text:
                key = label.lower()
                if key not in result:
                    result[key] = text.lower()

    return result


def extract_entities(text: str) -> dict[str, str]:
    settings = get_settings()
    if not settings.pioneer_api_key:
        return {}

    model_id = settings.pioneer_ner_model_id or "fastino/gliner2-base-v1"
    body = {
        "model_id": model_id,
        "text": text,
        "schema": {
            "entities": [
                "intent",
                "item",
                "brand",
                "connector",
                "duration",
                "rental_fee",
            ],
            "threshold": 0.4,
        },
    }
    headers = {
        "X-API-Key": settings.pioneer_api_key,
        "Content-Type": "application/json",
    }

    try:
        data = _do_post(INFERENCE_URL, headers, body)
    except Exception:
        return {}

    return _parse_entities(data)


def _entity_spans(data: dict[str, Any]) -> list[tuple[str, str]]:
    spans: list[tuple[str, str]] = []

    entities = data.get("entities")
    if isinstance(entities, list):
        for item in entities:
            if not isinstance(item, dict):
                continue
            text = item.get("text") or item.get("span")
            if isinstance(text, str) and text:
                spans.append((text, text))
        return spans

    if isinstance(entities, dict):
        for values in entities.values():
            text = _first_text(values)
            if text:
                spans.append((text, text))

    predictions = data.get("predictions")
    if isinstance(predictions, list):
        for item in predictions:
            if not isinstance(item, dict):
                continue
            text = item.get("span") or item.get("text")
            if isinstance(text, str) and text:
                spans.append((text, text))

    return spans


def redact_pii(text: str) -> str:
    settings = get_settings()
    if not settings.pioneer_api_key:
        return text

    model_id = (
        settings.pioneer_pii_model_id or "fastino/gliner2-privacy-filter-PII-multi"
    )
    body = {
        "model_id": model_id,
        "text": text,
        "schema": {
            "entities": ["person", "email", "phone_number"],
            "threshold": 0.4,
        },
    }
    headers = {
        "X-API-Key": settings.pioneer_api_key,
        "Content-Type": "application/json",
    }

    try:
        data = _do_post(INFERENCE_URL, headers, body)
    except Exception:
        return text

    spans = _entity_spans(data)
    if not spans:
        return text

    result = text
    for original, _ in sorted(spans, key=lambda pair: len(pair[0]), reverse=True):
        result = result.replace(original, "[redacted]")

    return result
