from __future__ import annotations

from unittest.mock import patch

import pytest

from app import pioneer_client


@pytest.fixture(autouse=True)
def _reset_http():
    pioneer_client.set_http(None)
    yield
    pioneer_client.set_http(None)


def test_empty_pioneer_key_guard_returns_true() -> None:
    with patch("app.pioneer_client.get_settings") as mock_settings:
        mock_settings.return_value.pioneer_api_key = ""
        mock_settings.return_value.pioneer_guard_model_id = "fastino/gliguard-LLMGuardrails-300M"
        assert pioneer_client.guard_is_safe("anything") is True


def test_empty_pioneer_key_extract_returns_empty() -> None:
    with patch("app.pioneer_client.get_settings") as mock_settings:
        mock_settings.return_value.pioneer_api_key = ""
        mock_settings.return_value.pioneer_ner_model_id = "fastino/gliner2-base-v1"
        assert pioneer_client.extract_entities("need hdmi") == {}


def test_guard_unsafe_when_prompt_safety_unsafe() -> None:
    def fake_post(url: str, headers: dict, body: dict) -> dict:
        return {
            "classifications": [
                {"label": "prompt_safety", "value": "unsafe", "confidence": 0.99},
                {"label": "jailbreak_detection", "value": "benign", "confidence": 0.9},
            ]
        }

    pioneer_client.set_http(fake_post)
    with patch("app.pioneer_client.get_settings") as mock_settings:
        mock_settings.return_value.pioneer_api_key = "test-key"
        mock_settings.return_value.pioneer_guard_model_id = "fastino/gliguard-LLMGuardrails-300M"
        assert pioneer_client.guard_is_safe("bad prompt") is False


def test_guard_unsafe_when_jailbreak_not_benign() -> None:
    def fake_post(url: str, headers: dict, body: dict) -> dict:
        return {
            "classifications": [
                {"label": "prompt_safety", "value": "safe", "confidence": 0.99},
                {"label": "jailbreak_detection", "value": "jailbreak", "confidence": 0.9},
            ]
        }

    pioneer_client.set_http(fake_post)
    with patch("app.pioneer_client.get_settings") as mock_settings:
        mock_settings.return_value.pioneer_api_key = "test-key"
        mock_settings.return_value.pioneer_guard_model_id = "fastino/gliguard-LLMGuardrails-300M"
        assert pioneer_client.guard_is_safe("jailbreak attempt") is False


def test_extract_hdmi_entity_list_shape() -> None:
    def fake_post(url: str, headers: dict, body: dict) -> dict:
        return {"entities": [{"label": "item", "text": "hdmi"}]}

    pioneer_client.set_http(fake_post)
    with patch("app.pioneer_client.get_settings") as mock_settings:
        mock_settings.return_value.pioneer_api_key = "test-key"
        mock_settings.return_value.pioneer_ner_model_id = "fastino/gliner2-base-v1"
        assert pioneer_client.extract_entities("need an hdmi") == {"item": "hdmi"}


def test_extract_entities_dict_shape() -> None:
    def fake_post(url: str, headers: dict, body: dict) -> dict:
        return {"entities": {"item": ["hdmi"]}}

    pioneer_client.set_http(fake_post)
    with patch("app.pioneer_client.get_settings") as mock_settings:
        mock_settings.return_value.pioneer_api_key = "test-key"
        mock_settings.return_value.pioneer_ner_model_id = "fastino/gliner2-base-v1"
        assert pioneer_client.extract_entities("hdmi please") == {"item": "hdmi"}


def test_extract_entities_predictions_shape() -> None:
    def fake_post(url: str, headers: dict, body: dict) -> dict:
        return {"predictions": [{"label": "item", "span": "hdmi"}]}

    pioneer_client.set_http(fake_post)
    with patch("app.pioneer_client.get_settings") as mock_settings:
        mock_settings.return_value.pioneer_api_key = "test-key"
        mock_settings.return_value.pioneer_ner_model_id = "fastino/gliner2-base-v1"
        assert pioneer_client.extract_entities("hdmi cable") == {"item": "hdmi"}


def test_guard_fail_open_on_http_error() -> None:
    def fake_post(url: str, headers: dict, body: dict) -> dict:
        raise RuntimeError("network down")

    pioneer_client.set_http(fake_post)
    with patch("app.pioneer_client.get_settings") as mock_settings:
        mock_settings.return_value.pioneer_api_key = "test-key"
        mock_settings.return_value.pioneer_guard_model_id = "fastino/gliguard-LLMGuardrails-300M"
        assert pioneer_client.guard_is_safe("hello") is True


def test_redact_pii_replaces_spans() -> None:
    def fake_post(url: str, headers: dict, body: dict) -> dict:
        return {
            "entities": [
                {"label": "person", "text": "Alice", "start": 11, "end": 16},
            ]
        }

    pioneer_client.set_http(fake_post)
    with patch("app.pioneer_client.get_settings") as mock_settings:
        mock_settings.return_value.pioneer_api_key = "test-key"
        mock_settings.return_value.pioneer_pii_model_id = "fastino/gliner2-privacy-filter-PII-multi"
        result = pioneer_client.redact_pii("Contact Alice please")
        assert "[redacted]" in result
        assert "Alice" not in result
