"""No network or player credentials: signed CSR2 service builder regression tests."""
from __future__ import annotations

import base64
import hashlib
import hmac
from collections import OrderedDict
from urllib.parse import parse_qs

import pytest

from csr2cdn._service_auth import (
    DEFAULT_NMCLIENT_ID, PortalCredentials, ServiceAuthError,
    prepare_portal_request, _prepare_signed_json,
)


ZID = "12345678901"  # synthetic, never use a real player ID in fixtures
PSK = "0" * 32
SECURITY = "1" * 32
EXPIRY = 2000000000
AUTH = base64.b64encode(f"head|nm|{ZID}|csr2|{EXPIRY}".encode()).decode("ascii")


def example_portal_doc(zid=ZID):
    token = base64.b64encode(f"head|nm|{zid}|csr2|{EXPIRY}".encode()).decode("ascii")
    return {"responseData": {"zynga": {"zauth": token, "zauthPidVToken": "SYNTHETIC"},
                             "psk": PSK, "securityHash": SECURITY}}


def example_creds():
    return PortalCredentials.from_response(ZID, example_portal_doc(), now=1700000000)


def test_portal_request_registered_client_not_per_player():
    left = prepare_portal_request(ZID, unix_time=1700000000, utc_offset="+0.00")
    right = prepare_portal_request("98765432109", unix_time=1700000000, utc_offset="+0.00")
    a = parse_qs(left.body.decode("utf8"), keep_blank_values=True)
    b = parse_qs(right.body.decode("utf8"), keep_blank_values=True)
    assert a["nmClientId"] == [DEFAULT_NMCLIENT_ID] == b["nmClientId"]
    assert a["zid"] == [""]
    assert a["zidResolveConflict"] == [ZID]
    assert b["zidResolveConflict"] == ["98765432109"]
    assert a["securityHash"] == b["securityHash"]
    assert a["productVersion"] == ["6.8.0"]
    assert "session" not in repr(left).lower()
    assert "securityHash" not in repr(left)


def test_portal_requires_player_id_and_registered_client_format():
    with pytest.raises(ServiceAuthError):
        prepare_portal_request("", unix_time=1700000000)
    with pytest.raises(ServiceAuthError):
        prepare_portal_request(ZID, nm_client_id="not registered")
    with pytest.raises(ServiceAuthError):
        prepare_portal_request(ZID, portal_url="http://example.invalid")


def test_parse_response_and_mask_tokens():
    creds = example_creds()
    assert creds.player_id == ZID
    assert creds.pid_validation_token == "SYNTHETIC"
    assert creds.expires_at == EXPIRY
    assert creds.user_psk == "1" * 32
    assert AUTH not in repr(creds)
    assert creds.user_psk not in repr(creds)
    # NM token claims and caller-selected CSR2 PlayerIDs use distinct identity
    # namespaces. A registered client can select an authorized game PlayerID.
    # The token must still be well formed and service headers remain caller-bound.
    foreign_claim = PortalCredentials.from_response(ZID, example_portal_doc("5555555"), now=1700000000)
    assert foreign_claim.player_id == ZID
    assert _prepare_signed_json(foreign_claim, "test/readonly", {}, unix_time=1700000000,
                                nonce=1).headers["PlayerID"] == ZID
    with pytest.raises(ServiceAuthError, match="expired"):
        PortalCredentials.from_response(ZID, example_portal_doc(), now=EXPIRY + 1)
    with pytest.raises(ServiceAuthError):
        PortalCredentials.from_response(ZID, {"responseData": {}}, now=1700000000)
    with pytest.raises(ServiceAuthError):
        PortalCredentials.from_response(ZID, {"zauth": "garbled", "zauthPidVToken": "x", "psk": PSK, "securityHash": SECURITY})


def test_signed_read_request_independent_hmac_vector():
    params = OrderedDict([("app_ver", "6.8.0"), ("label", "café")])
    req = _prepare_signed_json(example_creds(), "test/readonly", params,
                               unix_time=1700000000, nonce=12345)
    assert req.body == b'{"app_ver":"6.8.0","label":"caf\xc3\xa9"}'
    md5_digest = base64.b64encode(hashlib.md5(req.body).digest()).decode("ascii")
    to_sign = ZID + "POST" + req.url + "1700000000" + "12345" + md5_digest
    expected = base64.b64encode(hmac.new(
        ("1" * 32).encode(), to_sign.encode(), hashlib.sha256,
    ).digest()).decode("ascii")
    assert req.headers["X-Signature"] == expected
    assert req.headers["PlayerID"] == ZID
    assert req.headers["X-Time"] == "1700000000"
    assert req.headers["X-Nonce"] == "12345"
    assert "SYNTHETIC" not in repr(req)
    assert req.body not in repr(req).encode()


def test_internal_signer_cannot_be_used_as_a_save_game_api():
    import csr2cdn._service_auth as auth
    assert "prepare_fetch_profile" not in auth.__all__
    assert not hasattr(auth, "prepare_fetch_profile")
    assert not hasattr(auth, "prepare_read_request")
    assert not hasattr(auth, "READ_ONLY_ROUTES")
    creds = example_creds()
    a = _prepare_signed_json(creds, "test/readonly", {"app_ver": "6.8.0"},
                             unix_time=1700000000, nonce=12345)
    b = _prepare_signed_json(creds, "test/readonly", {"app_ver": "6.8.0"},
                             web_api_url="https://other.example", unix_time=1700000000, nonce=12345)
    assert a.headers["X-Signature"] != b.headers["X-Signature"]


def test_reject_injected_player_id_and_invalid_routes():
    for player in ("123&admin=1", "123+456", "123%20", "123/456"):
        with pytest.raises(ServiceAuthError):
            prepare_portal_request(player, unix_time=1700000000)
    creds = example_creds()
    for route in ("../test", "test/?query=1", "", "https://example.invalid", "test//go"):
        with pytest.raises(ServiceAuthError):
            _prepare_signed_json(creds, route, {"app_ver": "6.8.0"})
    with pytest.raises(ServiceAuthError):
        _prepare_signed_json(creds, "test/readonly", {"app_ver": "6.8.0"},
                             web_api_url="https://example.invalid/subroute")
    with pytest.raises(ServiceAuthError):
        _prepare_signed_json(creds, "test/readonly", {}, nonce=0)
    with pytest.raises(ServiceAuthError):
        _prepare_signed_json(creds, "test/readonly", {}, unix_time=EXPIRY+1)


def test_caller_can_override_registered_nmclient():
    custom = "abcdef12" * 5
    req = prepare_portal_request(ZID, nm_client_id=custom, unix_time=1700000000)
    assert parse_qs(req.body.decode("utf-8"))["nmClientId"] == [custom]


def test_token_format_and_expiry_are_still_checked():
    def encoded(value):
        return base64.b64encode(value.encode()).decode()
    for raw in ("head|other|NM|csr2|2000000000",
                "head|nm|NM||2000000000",
                "head|nm||csr2|2000000000",
                "head|nm|NM|csr2|invalid"):
        doc = example_portal_doc()
        doc["responseData"]["zynga"]["zauth"] = encoded(raw)
        with pytest.raises(ServiceAuthError):
            PortalCredentials.from_response(ZID, doc, now=1700000000)
    doc = example_portal_doc()
    doc["responseData"]["zynga"]["zauth"] = encoded("head|nm|NM|csr2|1700000000")
    with pytest.raises(ServiceAuthError, match="expired"):
        PortalCredentials.from_response(ZID, doc, now=1700000000)
