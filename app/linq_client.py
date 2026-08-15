from __future__ import annotations

from dataclasses import dataclass

from app.config import get_settings

LINQ_API_BASE = "https://api.linqapp.com/api/partner/v3"


@dataclass
class PaymentRequest:
    id: str
    checkout_url: str


class FakeLinq:
    def __init__(self) -> None:
        self.texts: list[tuple[str, str]] = []
        self.links: list[tuple[str, str]] = []
        self.payments: list[dict] = []
        self.locations: list[str] = []

    def send_text(self, chat_id: str, text: str) -> None:
        self.texts.append((chat_id, text))

    def send_link(self, chat_id: str, url: str) -> None:
        self.links.append((chat_id, url))

    def request_location(self, chat_id: str) -> None:
        self.locations.append(chat_id)

    def create_payment_request(self, amount_cents: int, description: str, metadata: dict) -> PaymentRequest:
        self.payments.append({"amount": amount_cents, "description": description, "metadata": metadata})
        return PaymentRequest(id="pr_test", checkout_url="https://zero.linqapp.com/pay/test")


_gateway: FakeLinq | None = None


def set_linq_gateway(gateway: FakeLinq | None) -> None:
    global _gateway
    _gateway = gateway


def _live_post(path: str, payload: dict) -> dict:
    import httpx

    settings = get_settings()
    response = httpx.post(
        f"{LINQ_API_BASE}{path}",
        headers={
            "Authorization": f"Bearer {settings.linq_api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=20.0,
    )
    response.raise_for_status()
    return response.json()


def send_text(chat_id: str, text: str) -> None:
    if _gateway is not None:
        _gateway.send_text(chat_id, text)
        return
    _live_post(f"/chats/{chat_id}/messages", {"message": {"parts": [{"type": "text", "value": text}]}})


def send_link(chat_id: str, url: str) -> None:
    if _gateway is not None:
        _gateway.send_link(chat_id, url)
        return
    _live_post(f"/chats/{chat_id}/messages", {"message": {"parts": [{"type": "link", "value": url}]}})


def create_payment_request(amount_cents: int, description: str, metadata: dict) -> PaymentRequest:
    if _gateway is not None:
        return _gateway.create_payment_request(amount_cents, description, metadata)
    data = _live_post(
        "/payment_requests",
        {
            "amount": amount_cents,
            "currency": "usd",
            "description": description,
            "metadata": metadata,
        },
    )
    return PaymentRequest(id=str(data["id"]), checkout_url=str(data["checkout_url"]))


def request_location(chat_id: str) -> None:
    if _gateway is not None:
        _gateway.request_location(chat_id)
        return
    _live_post(f"/chats/{chat_id}/location/request", {})
