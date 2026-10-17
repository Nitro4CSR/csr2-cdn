"""Native-traced player profile RP must not be substituted for seasonal crew RP."""
import json
import pytest
from csr2cdn.service_models import CrewMembers
from csr2cdn.live_validation import run_live


def _roster():
    return CrewMembers.from_response("C", {"crewMembers": [
        {"player_uid": "SECRET-UID-1", "name": "PRIVATE-NICKNAME-1", "role": "LEADER",
         "level": 410, "player_rp": 123456, "season_pass_rp_boost": 2},
        {"player_uid": "SECRET-UID-2", "name": "PRIVATE-NICKNAME-2", "role": "ADMIN",
         "level": 80, "player_rp": "0", "season_pass_rp_boost": 9},
        {"player_uid": "SECRET-UID-3", "name": "PRIVATE-NICKNAME-3", "role": "MEMBER",
         "level": 40, "player_rp": "bad"},
    ]})


def test_profile_rp_stays_distinct_from_season_and_native_alltime():
    roster = _roster()
    assert [m.player_rp for m in roster.members] == [123456, 0, None]
    assert [m.crew_rp for m in roster.members] == [None, None, None]
    assert [m.rp_all_time for m in roster.members] == [None, None, None]
    assert [m.role_normalized for m in roster.members] == ["LEADER", "ADMIN", "MEMBER"]
    assert dict(roster.wire_rp_schema_keys) == {"player_rp": 3, "season_pass_rp_boost": 2}


def test_explicit_season_is_not_overridden_by_profile_stat():
    roster = CrewMembers.from_response("C", {"crewMembers": [
        {"role": "ADMIN", "RP_season": 321, "player_rp": 10000000},
        {"role": "MEMBER", "RP": 1234, "player_rp": 99999},
    ]})
    assert [(m.crew_rp, m.crew_rp_source, m.rp_all_time, m.player_rp)
            for m in roster.members] == [
        (321, "RP_season", None, 10000000),
        (1234, "RP", 1234, 99999),
    ]


def test_private_validation_adds_only_profile_rp_coverage():
    roster = _roster()
    class Services:
        def __init__(self, *args, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def get_crew_members(self, crew_uid=None): return roster
    result = run_live("SECRET-UID-1", skip_metadata=True, crew_uid="C", services_factory=Services)
    crew = result["checks"]["crew"]
    assert crew["status"] == "ok"
    assert crew["player_profile_rp_populated"] == 2
    assert crew["crew_rp_populated"] == 0
    assert crew["rp_all_time_populated"] == 0
    assert crew["role_recognized"] == 3
    dump = json.dumps(result)
    assert all(s not in dump for s in ("SECRET-UID", "PRIVATE-NICKNAME", "123456", "player_rp"))


def test_profile_boolean_and_malformed_values_are_absent():
    roster = CrewMembers.from_response("C", {"crewMembers": [
        {"player_rp": True}, {"player_rp": "not-an-int"}, {"player_rp": 0}
    ]})
    assert [m.player_rp for m in roster.members] == [None, None, 0]
