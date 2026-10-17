"""Native-traced seasonal field candidates. All crew records are synthetic."""
import json

import pytest

from csr2cdn import CSR2Services, CrewMembers, GCCCrewStandings, ServiceResponseError
from csr2cdn.live_validation import main, run_live


def _roster(rows):
    return CrewMembers.from_response("HIDDEN_CREW_ID", {"crewMembers": rows})


def test_native_priority_cc_contrib_over_score_and_statistical_separation():
    rows = [
        {"player_uid": "SECRET_1", "name": "SECRET_NAME_1", "cc_contrib": "0", "score": 900,
         "RP": 5000000, "player_rp": 200000},
        {"player_uid": "SECRET_2", "name": "SECRET_NAME_2", "score": "75", "rp": 1500},
        {"player_uid": "SECRET_3", "name": "SECRET_NAME_3", "cc_contrib": "188", "score": 100},
        {"player_uid": "SECRET_4", "name": "SECRET_NAME_4", "player_rp": 60000},
    ]
    roster = _roster(rows)
    assert [(m.season_crew_rp_candidate, m.season_crew_rp_source)
            for m in roster.members] == [(0, "cc_contrib"), (75, "score"), (188, "cc_contrib"), (None, None)]
    # Existing ambiguous RP remains source-labelled and is never inferred from profile or score.
    assert [(m.crew_rp, m.rp_all_time) for m in roster.members] == [
        (5000000, 5000000), (1500, None), (None, None), (None, None)]
    counts = roster.wire_rp_diagnostics
    assert counts["dictionary_rows"] == 4
    assert counts["cc_contrib_present"] == 2
    assert counts["cc_contrib_numeric"] == 2
    assert counts["score_present"] == 3
    assert counts["score_numeric"] == 3
    assert counts["cc_contrib_and_score_present"] == 2
    assert counts["native_season_candidate_numeric"] == 3
    assert counts["native_season_candidate_from_cc_contrib"] == 2
    assert counts["native_season_candidate_from_score"] == 1
    assert roster.wire_rp_schema_keys == {
        "cc_contrib": 2, "player_rp": 2, "score": 3,
    }


@pytest.mark.parametrize("value", [True, False, -1, -1.0, 1.5, 1.0, "1.0", "-2", "not RP", "", None, {}, 2**64])
def test_malformed_or_nonintegral_contribution_cannot_be_promoted(value):
    roster = _roster([{"score": 20, "cc_contrib": value}])
    member = roster.members[0]
    assert member.season_crew_rp_candidate is None
    assert member.season_crew_rp_source == "cc_contrib"
    assert roster.wire_rp_diagnostics["native_season_candidate_numeric"] == 0
    assert roster.wire_rp_diagnostics["cc_contrib_null" if value is None else "cc_contrib_invalid"] == 1


def test_missing_keys_and_compact_rp_never_become_season_rp():
    compact = ["SECRET_ID", "PRIVATE", "SECRET_CREW", 5, 1234, 3, 6, 12, 40, 99]
    roster = _roster([compact, {"player_uid": "TWO", "RP_season": 1, "player_rp": 300},
                      {"player_uid": "THREE", "rp": 1000}])
    assert [m.season_crew_rp_candidate for m in roster.members] == [None, None, None]
    assert roster.wire_rp_diagnostics["native_season_candidate_numeric"] == 0


def test_private_probe_coverage_distinct_ids_and_no_candidate_values():
    private = "SECRET_ID_DO_NOT_OUTPUT"
    roster = _roster([
        {"player_uid": private, "name": "PRIVATE_NAME_DO_NOT_OUTPUT", "cc_contrib": 86420},
        {"player_uid": "ID_2", "score": 0},
        {"player_uid": "ID_2", "cc_contrib": None, "score": 77777},
        {"player_uid": "ID_4", "cc_contrib": 1.5},
    ])
    class Services:
        def __init__(self, *a, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def get_crew_members(self, crew_uid=None): return roster
    report = run_live(private, skip_metadata=True, crew_uid="C", crew_only=True,
                      crew_season_probe=True, crew_rp_schema=True, services_factory=Services)
    crew = report["checks"]["crew"]
    probe = crew["season_contribution_probe"]
    assert probe["records"] == probe["member_identity_rows"] == 4
    assert probe["distinct_preferred_member_identifiers"] == 3
    assert probe["duplicate_preferred_member_identifiers"] == 1
    assert probe["cc_contrib_candidate_rows"] == 1
    assert probe["score_fallback_candidate_rows"] == 1
    assert probe["season_candidate_numeric_rows"] == 2
    assert probe["season_candidate_zero_rows"] == 1
    assert probe["complete_identity_and_candidate_coverage"] is False
    assert probe["active_season_scope_verified"] is False
    assert probe["in_game_member_equivalence_verified"] is False
    assert probe["seasonal_crew_rp_release_unblocked"] is False
    serialized = json.dumps(report)
    for secret in (private, "PRIVATE_NAME_DO_NOT_OUTPUT", "86420", "77777"):
        assert secret not in serialized
    assert crew["wire_rp_diagnostics"]["cc_contrib_present"] == 3
    assert crew["wire_rp_diagnostics"]["cc_contrib_null"] == 1
    assert crew["wire_rp_diagnostics"]["cc_contrib_invalid"] == 1


def test_full_candidate_coverage_does_not_claim_live_validation():
    roster = _roster([
        {"player_uid": "A", "cc_contrib": 0},
        {"player_uid": "B", "cc_contrib": 99},
    ])
    from csr2cdn.live_validation import _crew_season_probe
    probe = _crew_season_probe(roster)
    assert probe["complete_identity_and_candidate_coverage"] is True
    assert probe["seasonal_crew_rp_release_unblocked"] is False


def test_gcc_native_total_and_rank_are_separate_from_alltime():
    response = {"results": [
        {"uid": "CREW_A", "name": "Crew A", "crew_rank": 2,
         "cc_rp": "1500000", "rp": 3000000, "score": 100},
        {"UID": "CREW_B", "Name": "Crew B", "crew_rank": 3, "score": 0},
        {"uid": "CREW_C", "crew_rank": 4, "cc_rp": "bad", "score": 300},
    ]}
    parsed = CSR2Services.decode_gcc_crew_standings(response)
    assert isinstance(parsed, GCCCrewStandings)
    assert [(r.crew_uid, r.rank, r.season_crew_rp_candidate, r.season_crew_rp_source, r.rp_all_time)
            for r in parsed.crews] == [
        ("CREW_A", 2, 1500000, "cc_rp", 3000000),
        ("CREW_B", 3, 0, "score", 0),
        ("CREW_C", 4, None, "cc_rp", 300),
    ]
    assert CSR2Services.decode_gcc_crew_standings({"responseData": [{"cc_rp": 0}]}).crews[0].season_crew_rp_candidate == 0
    with pytest.raises(ServiceResponseError):
        CSR2Services.decode_gcc_crew_standings({"entries": [{"cc_rp": 100}]})
    with pytest.raises(ServiceResponseError):
        CSR2Services.decode_gcc_crew_standings({"results": ["bad row"]})


def test_dry_run_with_probe_never_starts_network(capsys):
    assert main(["--crew-only", "--crew-season-probe"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["network_requests"] == 0
