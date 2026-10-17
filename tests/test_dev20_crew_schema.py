"""No player data leaves the privacy-filtered, opt-in schema census."""
import json
from csr2cdn.service_models import CrewMembers, _crew_rp_name_families
from csr2cdn.live_validation import run_live


def test_repeat_key_census_exposes_schema_only_and_does_not_guess_rp():
    rows = [{"player_uid": "PRIVATE_UID_"+str(i), "name": "SENSITIVE_NICK_"+str(i),
             "role": "ADMIN", "level": 100+i, "carPP": 400+i,
             "CarParts": 300+i, "rpBased": 1000+i,
             "RP_privateToken": 99999999, "rp123456": 1234, "rpSingleton": 2 if i == 0 else None}
            for i in range(29)]
    for row in rows[1:]: row.pop("rpSingleton")
    roster = CrewMembers.from_response("C", {"crewMembers": rows})
    key_counts = roster.wire_rp_schema_keys
    assert key_counts == {"CarParts": 29, "carPP": 29, "rpBased": 29}
    assert _crew_rp_name_families(key_counts) == {
        "car_performance_like": 58, "rp_boundary_like": 0,
        "other_substring_like": 29,
    }
    assert all(m.crew_rp is None for m in roster.members)
    serialized = json.dumps(key_counts)
    assert "PRIVATE_UID" not in serialized and "SENSITIVE_NICK" not in serialized
    assert "99999999" not in serialized and "privateToken" not in serialized


def test_opt_in_never_emits_values_and_default_omits_field_names():
    payload = {"crewMembers": [{"name": "VERY_PRIVATE_NICKNAME", "player_uid": "PRIVATE_USER",
                               "role": "LEADER", "carPP": 1000, "rpBased": 2000},
                              {"name": "OTHER_PRIVATE_NICKNAME", "player_uid": "PRIVATE2",
                               "role": "ADMIN", "carPP": 123, "rpBased": 234}]}
    roster = CrewMembers.from_response("C", payload)
    class Services:
        def __init__(self, *a, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *a): return None
        def get_crew_members(self, crew_uid=None): return roster
    kwargs = dict(skip_metadata=True, crew_uid="C", services_factory=Services)
    normal = run_live("PRIVATE_USER", **kwargs)
    assert "rp_schema_field_counts" not in normal["checks"]["crew"]
    opt = run_live("PRIVATE_USER", crew_rp_schema=True, **kwargs)
    assert opt["checks"]["crew"]["rp_schema_field_counts"] == {"carPP":2, "rpBased":2}
    printed = json.dumps(opt)
    for secret in ("VERY_PRIVATE_NICKNAME", "OTHER_PRIVATE_NICKNAME", "PRIVATE_USER", "2000", "123", "234"):
        assert secret not in printed
    assert all(m.crew_rp is None for m in roster.members)


def test_case_preservation_and_rare_dynamic_key_suppression():
    rows = [{"RP_season": "0", "RP": "10", "rp": "20", "role": "MEMBER",
             "rpPrivateName": 40, "aRpRare": 34, "rp6": 12},
            {"RP_season": 100, "RP": "11", "rp": 21, "role": "LEADER"}]
    out = CrewMembers.from_response("C", {"crewMembers": rows})
    assert out.wire_rp_schema_keys == {"RP":2, "RP_season":2, "rp":2}
    assert [m.crew_rp for m in out.members] == [0,100]
