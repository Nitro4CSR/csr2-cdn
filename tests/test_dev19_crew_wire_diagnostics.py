"""Tests for value-free, source-aware crew RP diagnostics."""
import json
from csr2cdn.service_models import CrewMembers
from csr2cdn.live_validation import run_live


def _coverage(rows):
    roster = CrewMembers.from_response("C", {"crewMembers": rows})
    return roster, roster.wire_rp_diagnostics


def test_live_like_missing_rp_does_not_create_zero_or_guess_another_numeric_field():
    rows = [{"player_uid": f"SENSITIVE{i}", "name": "PRIVATE", "level": 150,
             "role": 3, "career_earnings": 123456, "crewRPtotal": None} for i in range(29)]
    roster, counts = _coverage(rows)
    assert len(roster.members) == counts["dictionary_rows"] == 29
    assert all(m.crew_rp is None for m in roster.members)
    assert counts["native_RP_key_present"] == 0
    assert counts["native_rp_key_present"] == 0
    assert counts["known_crew_rp_alias_present"] == 0
    assert counts["other_rp_labeled_key_present"] == 29
    assert counts["rp_labeled_null"] == 29
    assert counts["role_source_number"] == 29
    assert "SENSITIVE" not in json.dumps(counts)
    assert "PRIVATE" not in json.dumps(counts)


def test_present_but_unparseable_is_distinct_from_absent():
    _, counts = _coverage([
        {"player_uid":"A","role":"LEADER","RP": "bad"},
        {"player_uid":"B","role":"ADMIN","RP": None},
        {"player_uid":"C","RP_season": 0},
    ])
    assert counts["native_RP_key_present"] == 2
    assert counts["explicit_season_rp_key_present"] == 1
    assert counts["rp_labeled_unparseable"] == 1
    assert counts["rp_labeled_null"] == 1
    assert counts["role_source_text"] == 2


def test_other_case_and_nested_rp_detected_but_not_mapped_without_authoritative_schema():
    roster, counts = _coverage([
        {"player_uid":"A", "Rp": 23, "stats": {"more": {"RP_season": 100}}},
        {"player_uid":"B", "stats": {"RP": 400}},
        {"player_uid":"C", "stats": {"Other": 1}},
    ])
    assert counts["other_rp_labeled_key_present"] == 1
    assert counts["rp_nested_labeled_rows"] == 2
    assert all(m.crew_rp is None for m in roster.members)


def test_native_compact_slot_coverage_keeps_zero():
    _, counts = _coverage([
        ["P", "n", "C", 10, 0, 2, 123, 22, 8, 12],
        ["P2", "n2", 0, 0, "123", 2, 22, 3, 12, 8, "a"],
        ["P3", "n3", 0, 0, None, 2, 22, 3, 12, 8, "a"],
    ])
    assert counts["compact_10_rows"] == 1
    assert counts["compact_11_rows"] == 2
    assert counts["compact_rp_slot_present"] == 2
    assert counts["compact_rp_slot_parseable"] == 2


def test_roster_coverage_appears_in_sanitized_live_summary_without_member_values():
    secret = "SENSITIVE_NICKNAME_1234"
    roster, _ = _coverage([{"player_uid":"PRIVATE_ZID", "name":secret,
                            "role": "LEADER", "RP": "not available"}])
    class Services:
        def __init__(self, *a, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *a): return None
        def get_crew_members(self, crew_uid=None): return roster
    report = run_live("PRIVATE_ZID", skip_metadata=True, crew_uid="C", services_factory=Services)
    checks = report["checks"]["crew"]
    assert checks["status"] == "ok"
    assert checks["wire_rp_diagnostics"]["rp_labeled_unparseable"] == 1
    encoded = json.dumps(report)
    assert secret not in encoded
    assert "PRIVATE_ZID" not in encoded
    assert "not available" not in encoded
    assert "leader" not in encoded.lower()
