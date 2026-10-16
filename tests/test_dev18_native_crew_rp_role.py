"""Native-key regressions; all data synthetic, no live roster records."""
from __future__ import annotations

import json
from dataclasses import asdict
from types import SimpleNamespace

import pytest

from csr2cdn import CrewMembers
from csr2cdn.live_validation import run_live
from csr2cdn.service_cli import _public_result


def _member(row):
    return CrewMembers.from_response("CREW", {"crewMembers": [{"player_uid": "NO_REAL_ID", **row}]}).members[0]


def test_native_dictionary_uses_uppercase_rp_at_rva_34a4a78():
    member = _member({"name": "TEST_NICKNAME", "level": "99", "RP": 120034,
                      "role": "ADMIN"})
    assert (member.nickname, member.player_rank, member.crew_rp) == (
        "TEST_NICKNAME", 99, 120034)
    assert member.crew_rp_source == "RP"
    assert member.rp_all_time == 120034
    assert member.role == "ADMIN" and member.role_normalized == "ADMIN"
    result = _public_result(CrewMembers("CREW", (member,)))
    assert result["members"][0]["crew_rp"] == 120034
    assert result["members"][0]["crew_rp_source"] == "RP"
    assert "extras" not in result["members"][0]


@pytest.mark.parametrize("row,want_rp,want_src,want_alltime", [
    ({"RP": 0}, 0, "RP", 0),
    ({"RP": "1,234"}, None, None, None),
    ({"RP": True}, None, None, None),
    ({"RP": "not a number"}, None, None, None),
    ({"RP": -12}, -12, "RP", -12),
    ({"RP_season": 20, "RP": 9000}, 20, "RP_season", 9000),
    ({"crewRP": 40, "RP": 9000}, 40, "crewRP", 9000),
    ({"RP": None, "rp": "90"}, 90, "rp", None),
    ({"rp": 0}, 0, "rp", None),
])
def test_case_sensitive_rp_and_source_priority(row, want_rp, want_src, want_alltime):
    m = _member(row)
    assert (m.crew_rp, m.crew_rp_source, m.rp_all_time) == (
        want_rp, want_src, want_alltime)


@pytest.mark.parametrize("value,expected", [
    ("NEWBIE", "NEWBIE"), ("MEMBER", "MEMBER"),
    ("senior", "SENIOR"), ("ADMIN", "ADMIN"),
    ("leader", "LEADER"),
    (0, "NEWBIE"), (1, "MEMBER"), (2, "SENIOR"),
    (3, "ADMIN"), (4, "LEADER"), ("4", "LEADER"),
    (-1, None), (5, None), ("unknown", None), (True, None),
])
def test_crew_role_known_names_and_native_integer_codes(value, expected):
    m = _member({"role": value})
    assert m.role_normalized == expected
    # Keep previous raw `role` representation unchanged.
    assert m.role == str(value)


def test_case_sensitive_role_key_alias():
    assert _member({"Role": "LEADER"}).role_normalized == "LEADER"


def test_native_compact_layout_remains_backwards_compatible():
    m = CrewMembers.from_response("CREW", {"crewMembers": [
        ["PLAYER", "N", "CREW", 0, "499", 2, 11, 20, 45, 10]
    ]}).members[0]
    assert m.crew_rp == 499 and m.crew_rp_source == "rp"
    assert m.rp_all_time is None


def test_sanitized_rp_and_role_coverage_contains_no_private_values():
    marker = "PRIVATE_DO_NOT_LEAK_998877"
    roster = CrewMembers.from_response("C", {"crewMembers": [
        {"player_uid": marker, "name": marker, "RP": 750001, "level": 18, "role": "LEADER"},
        {"player_uid": "OTHER", "name": "N", "RP": 0, "role": 3},
        {"player_uid": "THIRD", "name": "M", "RP_season": 1, "RP": 900, "role": "unknown"},
    ]})
    class Factory:
        def __init__(self, *args, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def get_crew_members(self, crew_uid=None): return roster
    result = run_live(marker, skip_metadata=True, crew_uid="C", services_factory=Factory)
    fields = result["checks"]["crew"]
    assert fields["records"] == 3
    assert fields["crew_rp_populated"] == 3
    assert fields["rp_all_time_populated"] == 3
    assert fields["rp_from_native_uppercase"] == 2
    assert fields["rp_from_explicit_season"] == 1
    assert fields["rp_from_crew_alias"] == 0
    assert fields["role_populated"] == 3
    assert fields["role_recognized"] == 2
    assert marker not in json.dumps(result)
    assert "750001" not in json.dumps(result)
    assert "900" not in json.dumps(result)


def test_no_rp_or_role_are_not_invented():
    m = _member({"name": "N", "level": 29})
    assert m.crew_rp is m.rp_all_time is m.crew_rp_source is None
    assert m.role is m.role_normalized is None
