"""Experimental CSR2 web-service authentication and read-only request builder.

Research implementation based on the user-supplied 6.7.1 save downloader and
static inspection of CSR2 6.8.0. There are *no* verified 6.8.0 live calls.

The NMG nmClientId is a **registered client identifier**, not a player-bound
credential. The default is the registered fallback from the supplied downloader.
A caller must supply a PlayerID. Portal responses are authoritative session
material and are never logged or written to disk by this module.

This module contains no save-game operations or enabled game-service routes.
Crew/Showdown/Prestige read contracts must be traced before exposing callers.
"""
from __future__ import annotations

import base64
import binascii
import re
import hashlib
import hmac
import json
import secrets
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional
from urllib.parse import quote, urlsplit

from csr2cdn.errors import Csr2CdnError

# Protocol observations from the user-provided downloader (6.7.1); these are
# not independently validated against the 6.8.0 production service.
PORTAL_URL = "https://csr2.core.nmgx.co.uk/fozzie/portal2.php"
WEB_API_URL = "https://prod-web.csr2.zynga.com"
DEFAULT_NMCLIENT_ID = "a4a591a4a2d56382b8db28d73b55f7f3ab508feb"
DEFAULT_AGENT = "Dalvik/2.1.0 (Linux; U; Android 13; Pixel Build/TQ3A.230805.001)"
_PROTOCOL_VERSION = "5"
_PRODUCT_NAME = "csr2"
_PRODUCT_PLATFORM = "googleplay"
_PORTAL_PRESHARED_KEY = "ngzmayqZgvgg8RF4qgDef9YhGNwBhhya"
# No live read operations have been verified for this package.
# Keep all signing helpers internal until explicit read-only contracts exist.


class ServiceAuthError(Csr2CdnError):
    """Invalid account/session material, without embedding sensitive values."""


def _player_id(value: str) -> str:
    result = str(value).strip()
    if (not result or result != str(value) or
            any(c.isspace() or c in "&=+#%?/\\\r\n" for c in result)):
        raise ServiceAuthError("a non-empty PlayerID is required")
    return result


def _registered_nmclient(value: str) -> str:
    value = str(value).strip().lower()
    if len(value) != 40 or any(c not in "0123456789abcdef" for c in value):
        raise ServiceAuthError("nmClientId must be a registered 40-character hex identifier")
    return value


def _https_url(url: str) -> str:
    url = str(url).rstrip("/")
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.netloc or parts.username or parts.password or parts.fragment or parts.query:
        raise ServiceAuthError("service base URL must be an HTTPS origin without credentials or query")
    return url


def _compact_json(data: Mapping[str, Any]) -> bytes:
    # Important: exact UTF-8 bytes and insertion order affect the MD5 and HMAC.
    return json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _portal_identities(nm_client_id: str) -> tuple[str, str, str]:
    seed = hashlib.sha256(nm_client_id.encode("utf-8")).hexdigest()
    return (
        seed[:16],
        str(uuid.uuid5(uuid.NAMESPACE_DNS, "csr2-vendor:" + nm_client_id)),
        str(uuid.uuid5(uuid.NAMESPACE_DNS, "csr2-ad:" + nm_client_id)),
    )


def prepare_portal_request(
    player_id: str,
    *,
    nm_client_id: str = DEFAULT_NMCLIENT_ID,
    app_version: str = "6.8.0",
    unix_time: Optional[int] = None,
    portal_url: str = PORTAL_URL,
    user_agent: str = DEFAULT_AGENT,
    utc_offset: Optional[str] = None,
) -> "PreparedRequest":
    """Build but DO NOT SEND a portal request for an explicitly supplied PlayerID.

    The default nmClientId is registered but not account-associated; the
    portal ``zidResolveConflict`` field chooses the requested PlayerID.
    """
    zid = _player_id(player_id)
    nmclient = _registered_nmclient(nm_client_id)
    if not app_version or not str(app_version).strip():
        raise ServiceAuthError("app_version is required")
    now = int(time.time()) if unix_time is None else int(unix_time)
    if utc_offset is None:
        local = time.localtime(now)
        seconds = -time.altzone if local.tm_isdst and time.daylight else -time.timezone
        utc_offset = f"{seconds / 3600.0:+.2f}"
    android_id, vendor_id, ad_id = _portal_identities(nmclient)
    idents = OrderedDict([
        ("androidId", {"id": android_id, "token": ""}),
        ("vendoridentifier", {"id": vendor_id, "token": ""}),
        ("adidentifier", {"id": ad_id, "token": ""}),
    ])
    ident_json = json.dumps(idents, separators=(",", ":"), ensure_ascii=False)
    identity_sha1 = hashlib.sha1(ident_json.encode("utf-8")).hexdigest()
    # Preserve the single working selection flow from the reference client.
    zid_field = ""
    security_preimage = identity_sha1 + zid_field + nmclient + _PRODUCT_NAME + _PRODUCT_PLATFORM + _PORTAL_PRESHARED_KEY
    security_hash = hashlib.sha1(security_preimage.encode("utf-8")).hexdigest()
    device_data = {
        "cpu": {"cores": 8, "family": "ARM64", "features": {}},
        "device": {
            "PRODUCT": "generic", "DEVICE": "generic", "BOARD": "generic",
            "MANUFACTURER": "Google", "BRAND": "google", "MODEL": "Pixel", "HARDWARE": "generic",
        },
    }
    esc = lambda value: quote(str(value), safe="-_.~")
    fields = [
        ("protocolVersion", _PROTOCOL_VERSION),
        ("productVersion", str(app_version)),
        ("deviceType", "mobile"),
        ("deviceOS", "Android"),
        ("deviceOSVersion", "13"),
        ("deviceResolution", "1080x2400"),
        ("deviceData", json.dumps(device_data, separators=(",", ":"), ensure_ascii=False)),
        ("countryCode", "US"), ("language", "en"),
        ("zid", zid_field), ("nmClientId", nmclient),
        ("productName", _PRODUCT_NAME), ("productPlatform", _PRODUCT_PLATFORM),
        ("securityHash", security_hash), ("pnsToken", ""), ("pnsData", ""),
        ("idents", ident_json), ("clientUtc", str(now)), ("utcOffset", utc_offset),
        ("zidResolveConflict", zid), ("firstLaunch", "0"),
        ("campaignData", ""), ("eosEnv", ""), ("segmentsParams", "{}"), ("a", "1"),
    ]
    # The downloader emitted several literal fields (segmentsParams={});
    # quote *only* the fields it percent-encoded, not the complete form.
    quoted_names = {"productVersion", "deviceData", "idents"}
    body = "&".join(f"{k}={esc(v) if k in quoted_names else v}" for k, v in fields).encode("utf-8")
    return PreparedRequest(
        url=_https_url(portal_url), body=body,
        headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": user_agent,
                 "Accept-Encoding": "gzip, deflate"},
    )


def _claim_from_token(token: str) -> tuple[str, int]:
    try:
        if not isinstance(token, str) or len(token) > 16384:
            raise ValueError("unsupported token")
        raw = base64.b64decode(token, validate=True).decode("utf-8").split("|")
        if len(raw) < 5 or raw[1] != "nm" or not raw[2] or not raw[3]:
            raise ValueError("unsupported token")
        return raw[3], int(raw[4])
    except (ValueError, UnicodeError, binascii.Error) as exc:
        raise ServiceAuthError("unrecognized portal token format") from None


@dataclass(frozen=True)
class PortalCredentials:
    """Transient authenticated session; token/key values are omitted from repr."""

    player_id: str = field(repr=False)
    authorization: str = field(repr=False)
    pid_validation_token: str = field(repr=False)
    user_psk: str = field(repr=False)
    expires_at: int

    @classmethod
    def from_response(
        cls, player_id: str, response: Mapping[str, Any], *, now: Optional[int] = None,
    ) -> "PortalCredentials":
        zid = _player_id(player_id)
        doc = response.get("responseData", response)
        if not isinstance(doc, dict):
            raise ServiceAuthError("portal response is not an object")
        zynga = doc.get("zynga") if isinstance(doc.get("zynga"), dict) else {}
        auth = str(zynga.get("zauth") or doc.get("zauth") or "")
        pid = str(zynga.get("zauthPidVToken") or doc.get("zauthPidVToken") or "")
        if not auth or not pid:
            raise ServiceAuthError("portal response lacks session authorization")
        # This token names the portal's NM identity, not necessarily the
        # game PlayerID chosen through zidResolveConflict. The reference
        # client uses the caller's selected PlayerID in the service headers
        # and validates it with the portal-supplied PID validation token.
        # Reject invalid/expired/wrong-product tokens, but do not incorrectly
        # equate the two different identity namespaces.
        _, expiry = _claim_from_token(auth)
        current = int(time.time()) if now is None else int(now)
        if expiry and expiry <= current:
            raise ServiceAuthError("portal authorization token is expired")
        psk = str(doc.get("psk", ""))
        sec_hash = str(doc.get("securityHash", doc.get("security_hash", "")))
        if len(psk) < 32 or len(sec_hash) < 32:
            raise ServiceAuthError("portal response lacks signing material")
        try:
            key = "".join(
                f"{int(psk[i:i+8], 16) ^ int(sec_hash[i:i+8], 16):08x}"
                for i in range(0, 32, 8)
            )
        except ValueError as exc:
            raise ServiceAuthError("portal signing material is not hexadecimal") from exc
        return cls(zid, auth, pid, key, expiry)


@dataclass(frozen=True)
class PreparedRequest:
    """Prepared bytes and headers. Do not log its fields: they carry credentials."""

    url: str = field(repr=False)
    body: bytes = field(repr=False)
    headers: Mapping[str, str] = field(repr=False)


def _prepare_signed_json(
    creds: PortalCredentials,
    route: str,
    params: Mapping[str, Any],
    *,
    web_api_url: str = WEB_API_URL,
    unix_time: Optional[int] = None,
    nonce: Optional[int] = None,
    user_agent: str = DEFAULT_AGENT,
    language: str = "en-US,en;q=0.9",
) -> PreparedRequest:
    """Internal signing primitive for synthetic offline test vectors.

    This does not send traffic. Callers should only use the separately
    validated, allowlisted game-service read contracts.
    """
    if not isinstance(route, str) or not re.fullmatch(r"[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*", route):
        raise ServiceAuthError("invalid route format")
    if not isinstance(params, Mapping):
        raise TypeError("params must be a mapping")
    base = _https_url(web_api_url)
    if urlsplit(base).path not in ("", "/"):
        raise ServiceAuthError("web service base must be an HTTPS origin")
    url = f"{base}/{route}"
    current = int(time.time()) if unix_time is None else int(unix_time)
    if creds.expires_at and creds.expires_at <= current:
        raise ServiceAuthError("portal authorization token is expired")
    n = secrets.randbelow(2 ** 31 - 1) + 1 if nonce is None else int(nonce)
    if n <= 0:
        raise ServiceAuthError("nonce must be positive")
    body = _compact_json(params)
    digest = base64.b64encode(hashlib.md5(body).digest()).decode("ascii")
    canonical = creds.player_id + "POST" + url + str(current) + str(n) + digest
    signature = base64.b64encode(hmac.new(
        creds.user_psk.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256,
    ).digest()).decode("ascii")
    return PreparedRequest(url=url, body=body, headers={
        "User-Agent": user_agent,
        "Authorization": f"token {creds.authorization}",
        "Accept-Language": language,
        "PlayerID": creds.player_id,
        "PIDValidationToken": creds.pid_validation_token,
        "Content-Type": "application/json",
        "Accept-Encoding": "gzip, deflate",
        "X-Nonce": str(n), "X-Time": str(current), "X-Signature": signature,
    })


__all__ = [
    "DEFAULT_NMCLIENT_ID", "PORTAL_URL", "WEB_API_URL",
    "ServiceAuthError", "PortalCredentials", "PreparedRequest",
    "prepare_portal_request",
]
