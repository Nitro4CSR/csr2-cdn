"""Read-only, privacy-safe crew profile decoding regression coverage.

All examples are constructed fixtures. No real account or player values.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from types import SimpleNamespace

import pytest

from csr2cdn import CrewMembers
from csr2cdn.service_cli import _public_result
from csr2cdn.live_validation import run_live


def test_native_dict_names_rp_level_and_existing_car_are_public():
    response = {"responseData": {"crewUID": "CREW_PRIVATE", "crewMembers": [
        {"player_uid": "PRIVATE_PLAYER", "name": "PRIVATE_NICKNAME",
         "rp": "150000", "level": "450", "car_pp": 700, "car_ep": 400},
    ]}}
    roster = CrewMembers.from_response("CREW_PRIVATE", response)
    member = roster.members[0]
    assert (member.name, member.nickname, member.crew_rp, member.player_rank) == (
        "PRIVATE_NICKNAME", "PRIVATE_NICKNAME", 150000, 450)
    assert member.car.pp == 700 and member.car.ep == 400
    public = _public_result(roster)["members"][0]
    assert public["crew_rp"] == 150000
    assert public["player_rank"] == 450
    assert public["nickname"] == "PRIVATE_NICKNAME"
    assert "extras" not in public


@pytest.mark.parametrize("keys,expected", [
    ({"playerName": "Alt", "crewRP": 0, "playerLevel": 12}, ("Alt", 0, 12)),
    ({"nickname": "Alt2", "crew_rp": "99", "player_rank": 2}, ("Alt2", 99, None)),
    ({"displayName": "Alt3", "rp": "invalid", "level": "wrong"}, ("Alt3", None, None)),
    ({"name": "Alt4", "rp": True, "level": False}, ("Alt4", None, None)),
])
def test_known_dict_aliases_and_unverified_rank_key(keys, expected):
    obj = {"crewMembers": [{"zid": "PLAYER", **keys}]}
    member = CrewMembers.from_response("CREW", obj).members[0]
    assert (member.nickname, member.crew_rp, member.player_rank) == expected


def test_native_compact_10_11_layouts_are_typed():
    # Positional layouts as traced in native PlayerCrewMember.FromJSONList.
    a = ["USER", "Nickname", "CREW", 10, "2300", 2, 45, 12, "32", 1234]
    b = ["USER", "Nickname2", 10, 20, "9900", 3, 100, 42, 101, "54", "Hi"]
    members = CrewMembers.from_response("CREW", {"crewMembers": [a, b]}).members
    assert [(m.name, m.crew_rp, m.player_rank) for m in members] == [
        ("Nickname", 2300, 32), ("Nickname2", 9900, 54)]


def test_missing_values_remain_none_and_existing_positional_initialization_survives():
    a = CrewMembers.from_response("CREW", {"crewMembers": [{"zid": "USER", "name": "Name"}]}).members[0]
    assert a.name == a.nickname == "Name"
    assert a.crew_rp is None and a.player_rank is None
    # Do not relabel unqualified ranking position as player experience level.
    b = CrewMembers.from_response("CREW", {"crewMembers": [{"zid": "USER", "rank": 1}]}).members[0]
    assert b.player_rank is None


def test_crew_report_only_counts_optional_field_presence():
    private = "NEVER_PRINT_PRIVATE_NICKNAME"
    private_id = "NEVER_PRINT_PRIVATE_USER"
    roster = CrewMembers.from_response("SECRET_CREW", {"crewMembers": [
        {"zid": private_id, "name": private, "rp": 120, "level": 11},
        {"zid": "ANOTHER_ID", "nickname": "Other", "rp": 0},
        {"zid": "THIRD_ID", "level": 0},
    ]})
    class Fake:
        def __init__(self, player_id, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *exc): return None
        def get_crew_members(self, crew_uid=None): return roster
    report = run_live(private_id, skip_metadata=True, crew_uid="SECRET_CREW", services_factory=Fake)
    fields = report["checks"]["crew"]
    assert {k: v for k, v in fields.items() if k != "wire_rp_diagnostics"} == {"status": "ok", "records": 3, "nickname_populated": 2,
                      "crew_rp_populated": 2, "player_rank_populated": 2,
                      "rp_all_time_populated": 0, "player_profile_rp_populated": 0, "rp_from_native_uppercase": 0,
                      "rp_from_explicit_season": 0, "rp_from_crew_alias": 0, "role_populated": 0,
                      "role_recognized": 0}
    assert private not in json.dumps(report)
    assert private_id not in json.dumps(report)
    assert "SECRET_CREW" not in json.dumps(report)


def test_crew_only_skips_metadata_and_board_access():
    roster = CrewMembers.from_response("C", {"crewMembers": [{"name": "N", "rp": 50, "level": 22}]})
    class Service:
        def __init__(self, player_id, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *exc): return None
        def get_my_crew(self): return SimpleNamespace(in_crew=True)
        def get_crew_members(self): return roster
        def get_showdown_leaderboard(self, **kwargs): raise AssertionError("unexpected Showdown")
    r = run_live("USER", crew_only=True, services_factory=Service,
                 metadata_factory=lambda: (_ for _ in ()).throw(AssertionError("unexpected metadata")))
    assert r["checks"]["metadata"] == {"status": "skipped"}
    assert r["checks"]["showdown"] == {"status": "not_selected"}
    assert r["checks"]["prestige_cup"] == {"status": "not_selected"}
    assert r["checks"]["crew"]["crew_rp_populated"] == 1
