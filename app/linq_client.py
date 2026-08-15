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
        self.media: dict[str, bytes] = {}
        self.chat_locations: dict[str, tuple[float, float]] = {}

    def send_text(self, chat_id: str, text: str) -> None:
        self.texts.append((chat_id, text))

    def send_link(self, chat_id: str, url: str) -> None:
        self.links.append((chat_id, url))

    def request_location(self, chat_id: str) -> None:
        self.locations.append(chat_id)

    def create_payment_request(self, amount_cents: int, description: str, metadata: dict) -> PaymentRequest:
        self.payments.append({"amount": amount_cents, "description": description, "metadata": metadata})
        return PaymentRequest(id="pr_test", checkout_url="https://zero.linqapp.com/pay/test")

    def download_media(self, media_id: str) -> bytes:
        return self.media.get(media_id, b"fake-media-bytes")

    def get_location(self, chat_id: str) -> tuple[float, float] | None:
        return self.chat_locations.get(chat_id)


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


def _live_get(path: str):
    import httpx

    settings = get_settings()
    response = httpx.get(
        f"{LINQ_API_BASE}{path}",
        headers={"Authorization": f"Bearer {settings.linq_api_key}"},
        timeout=20.0,
    )
    response.raise_for_status()
    return response


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


def download_media(media_id: str) -> bytes:
    if _gateway is not None:
        return _gateway.download_media(media_id)
    return _live_get(f"/media/{media_id}").content


def get_location(chat_id: str) -> tuple[float, float] | None:
    """Last shared location for a 1:1 chat as (lat, lng). Linq sends [lng, lat]."""
    if _gateway is not None:
        return _gateway.get_location(chat_id)
    data = _live_get(f"/chats/{chat_id}/location").json() or {}
    if isinstance(data.get("location"), dict):
        data = data["location"]
    coords = data.get("coordinates") or []
    if len(coords) < 2:
        return None
    return float(coords[1]), float(coords[0])
