"""Signed photo URLs.

The dispute page is opened by a Terac worker with no account, so /media cannot sit
behind a login. Signing the id instead means a link only works if we minted it, and
a leaked Linq media id on its own fetches nothing.
"""

from __future__ import annotations

import hashlib
import hmac

from app.config import get_settings

_SIG_LEN = 16


def sign_media_id(media_id: str) -> str:
    secret = get_settings().internal_settle_secret.encode()
    return hmac.new(secret, media_id.encode(), hashlib.sha256).hexdigest()[:_SIG_LEN]


def media_url(media_id: str | None) -> str:
    if not media_id:
        return ""
    return f"/media/{media_id}?s={sign_media_id(media_id)}"


def media_signature_ok(media_id: str, provided: str | None) -> bool:
    return hmac.compare_digest(sign_media_id(media_id), provided or "")
