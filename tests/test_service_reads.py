"""Offline CSR2 6.8.0 native read-contract vectors; no live or private data."""
from __future__ import annotations

import base64
import json
from collections import OrderedDict

import pytest

from csr2cdn._service_auth import PortalCredentials
from csr2cdn._service_reads import (
    ReadContract, ReadContractError, StandingRange, crew_members_contract,
    prepare_read_contract, showdown_standings_contract,
)


def credentials():
    zid, exp = "12345678901", 2000000000
    token = base64.b64encode(f"head|nm|{zid}|csr2|{exp}".encode()).decode()
    return PortalCredentials.from_response(zid, {"responseData": {
        "zynga": {"zauth": token, "zauthPidVToken": "TEST_ONLY"},
        "psk": "0" * 32, "securityHash": "1" * 32,
    }}, now=1700000000)


def test_crew_route_and_keys_are_native_6_8_literals():
    c = crew_members_contract("crew123")
    assert c.route == "crews/viewMembers"
    assert list(c.params.items()) == [("crew_uid", "crew123"), ("app_ver", "6.8.0")]
    assert c.request_type == 3
    signed = prepare_read_contract(credentials(), c, unix_time=1700000000, nonce=4)
    assert signed.url.endswith("/crews/viewMembers")
    assert signed.body == b'{"crew_uid":"crew123","app_ver":"6.8.0"}'
    assert signed.headers["PlayerID"] == "12345678901"


def test_showdown_progress_matches_native_key_order():
    c = showdown_standings_contract("evnt-example---dsc", StandingRange(0, 0, 0, top=25))
    assert c.request_type == 5
    assert c.route == "leaderboard/evnt-example---dsc/view"
    assert list(c.params.items()) == [
        ("app_ver", "6.8.0"), ("top", 25), ("after", 0), ("before", 0), ("offset", 0),
    ]
    signed = prepare_read_contract(credentials(), c, unix_time=1700000000, nonce=5)
    assert json.loads(signed.body) == c.params
    assert signed.url.endswith("/view")


def test_showdown_preview_requires_score_and_omits_top_if_unset():
    c = showdown_standings_contract("weekly-1", StandingRange(0, -1, 2), preview=True, score=30)
    assert c.route == "leaderboard/weekly-1/preview"
    assert list(c.params.items()) == [
        ("app_ver", "6.8.0"), ("after", 0), ("before", -1), ("offset", 2), ("score", 30),
    ]
    assert prepare_read_contract(credentials(), c, unix_time=1700000000, nonce=6)
    with pytest.raises(ReadContractError, match="requires explicit score"):
        showdown_standings_contract("weekly-1", StandingRange(0, 0, 0), preview=True)
    with pytest.raises(ReadContractError, match="does not accept"):
        showdown_standings_contract("weekly-1", StandingRange(0, 0, 0), score=1)


@pytest.mark.parametrize("bad", ["", "../crews", "test/name", "a?debug=1", "a%2fb", "a.b", " name", "a&b"])
def test_no_user_controlled_routes_or_field_injection(bad):
    with pytest.raises(ReadContractError):
        crew_members_contract(bad)
    with pytest.raises(ReadContractError):
        showdown_standings_contract(bad, StandingRange(0, 0, 0))


def test_reject_invalid_range_types_and_implicit_defaults():
    for value in [True, 1.5, 2**35, -(2**31)-1]:
        with pytest.raises(ReadContractError):
            showdown_standings_contract("test", StandingRange(value, 0, 0))
    with pytest.raises(ReadContractError):
        showdown_standings_contract("test", StandingRange(0, 0, 0, top=-(2**31)))
    with pytest.raises(TypeError):
        StandingRange()
    with pytest.raises(ReadContractError):
        crew_members_contract("test", app_version="6.8.0\nInjected")


def test_signer_allowlist_blocks_save_and_score_write_routes():
    for route in ["users/fetchProfile", "leaderboard/season/score", "crews/kickMember"]:
        c = ReadContract(route, OrderedDict([("app_ver", "6.8.0")]), 5, "test")
        with pytest.raises(ReadContractError):
            prepare_read_contract(credentials(), c, unix_time=1700000000)


def test_signer_rejects_noncanonical_tampered_contracts():
    c = crew_members_contract("crew123")
    tampered = ReadContract(c.route, OrderedDict([("app_ver", "6.8.0"), ("crew_uid", "crew123")]), 3, c.operation)
    with pytest.raises(ReadContractError):
        prepare_read_contract(credentials(), tampered)
    badboard = ReadContract("leaderboard/test/view", {"app_ver": "6.8.0", "top": "25", "after": 0, "before": 0, "offset": 0}, 5, "test")
    with pytest.raises(ReadContractError):
        prepare_read_contract(credentials(), badboard)


def test_no_network_in_contract_builders(monkeypatch):
    import requests
    def no_network(*args, **kwargs):
        raise AssertionError("network invoked by offline request builder")
    monkeypatch.setattr(requests.sessions.Session, "request", no_network)
    c = crew_members_contract("crew123")
    prepare_read_contract(credentials(), c, unix_time=1700000000, nonce=1)


def test_native_arm64_range_constants():
    assert StandingRange.common().as_wire_params() == {"top": 10, "after": 5, "before": 5, "offset": 0}
    assert StandingRange.preview().as_wire_params() == {"after": 4, "before": 4, "offset": 0}
    assert StandingRange.top3_and_you().as_wire_params() == {"top": 3, "after": 0, "before": 0, "offset": 0}
    assert showdown_standings_contract("board", StandingRange.common()).params["top"] == 10
