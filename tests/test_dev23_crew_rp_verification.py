"""Dev23 explicit-print comparison tests use synthetic rosters only."""
import json

import pytest

from csr2cdn.crew_rp_verification import (
    _printable, make_member_report, make_gcc_report, verify, main, _table,
)
from csr2cdn.service_models import CrewMembers, OwnCrew


def _roster():
    return CrewMembers.from_response("synthetic_crew", {"crewMembers": [
        {"player_uid": "P1", "name": "MR ORANGE", "cc_contrib": 150, "player_rp": 98765, "level": 4309},
        {"player_uid": "P2", "name": "JAM", "cc_contrib": 50, "player_rp": 123, "level": 1210},
        {"player_uid": "P3", "name": "ZERO", "cc_contrib": 0, "score": 99, "player_rp": 234},
    ]})


def test_roster_print_candidates_sorted_and_sum_with_ui_delta():
    r = make_member_report(_roster(), reference_total=220, reference_rank=257,
                           expected_members=3, season_note="Manthey 911 Prestige Cup")
    assert r["roster_count"] == 3
    assert r["cc_contrib_numeric_rows"] == 3
    assert r["score_fallback_numeric_rows"] == 0
    assert r["complete_numeric_contribution_coverage"]
    assert r["all_identifiers_distinct_and_present"]
    assert r["sum_of_available_member_candidates"] == 200
    assert r["delta_member_sum_minus_ui_total"] == -20
    assert [row["member_name"] for row in r["rows"]] == ["MR ORANGE", "JAM", "ZERO"]
    assert r["rows"][2]["cc_contrib"] == 0
    assert r["rows"][2]["score_fallback"] is None  # cc_contrib overwrites score
    assert r["rows"][0]["player_rp"] != r["rows"][0]["cc_contrib"]
    assert r["season_scope_confirmed_by_server"] is False
    assert "P1" not in json.dumps(r)


def test_no_crew_missing_candidate_never_fake_total_match():
    r = make_member_report(CrewMembers.from_response("X", {"crewMembers": [
        {"player_uid": "a", "name": "A", "score": 2},
        {"player_uid": "b", "name": "B", "cc_contrib": None, "score": 10},
    ]}), reference_total=2, expected_members=2)
    assert r["complete_numeric_contribution_coverage"] is False
    assert r["sum_of_available_member_candidates"] == 2
    assert r["delta_member_sum_minus_ui_total"] is None
    assert r["score_fallback_numeric_rows"] == 1
    assert r["rows"][1]["candidate_source"] == "cc_contrib"


def test_duplicate_member_ids_not_reported_as_distinct():
    r = make_member_report(CrewMembers.from_response("X", {"crewMembers": [
        {"player_uid": "same", "cc_contrib": 20}, {"player_uid": "same", "cc_contrib": 30},
    ]}))
    assert r["all_identifiers_distinct_and_present"] is False


def test_gcc_supplied_json_prints_multiple_crews_without_live_request():
    raw = {"results": [
        {"uid": "own", "name": "Own", "cc_rp": 37448821, "crew_rank": 257, "rp": 99999999},
        {"uid": "other", "name": "Other", "cc_rp": 45000, "crew_rank": 258},
    ]}
    r = make_gcc_report(raw, own_crew_uid="own", reference_total=37448821, reference_rank=257)
    assert len(r["rows"]) == 2
    assert r["matched_own_crew_records"] == 1
    assert r["own_crew_cc_rp_minus_ui_total"] == 0
    assert r["own_crew_rank_matches_ui"] is True
    assert r["active_season_verified"] is False
    assert r["rows"][1]["matches_own_crew_id"] is False
    assert '"uid"' not in json.dumps(r)


def test_own_crew_routes_called_once_and_no_speculative_live_leaderboard():
    called = []
    class FakeSvc:
        def __init__(self, *a, **kw):
            called.append(("init", kw["allow_network"]))
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def get_my_crew(self):
            called.append("crews/checkUserCrew")
            return OwnCrew("own", extras={"crew_rank": 257, "cc_rp": 37448821, "token": "SECRET"})
        def get_crew_members(self):
            called.append("crews/viewMembers")
            return _roster()
    result = verify(player_id="SECRET_PLAYER_ID", execute=True, services_factory=FakeSvc,
                    reference_total=220, reference_rank=257, expected_members=3)
    assert called == [("init", True), "crews/checkUserCrew", "crews/viewMembers"]
    assert result["own_crew_field_candidates"] == {"cc_rp": 37448821, "crew_rank": 257}
    txt = json.dumps(result)
    assert "SECRET_PLAYER_ID" not in txt and "SECRET" not in txt
    assert result["member_response"]["delta_member_sum_minus_ui_total"] == -20
    assert "gcc_supplied_response" not in result


def test_explicit_print_optin_dry_run_no_network(capsys):
    assert main([]) == 0
    assert json.loads(capsys.readouterr().out)["network_requests"] == 0
    with pytest.raises(SystemExit) as exc:
        main(["--execute"])
    assert exc.value.code == 2
    assert _printable("abc\x1b[31m\u202esecret") == "abc?[31m?secret"


def test_gcc_file_only_mode_does_not_authenticate(tmp_path, capsys):
    p = tmp_path / "gcc.json"
    p.write_text(json.dumps({"results": [{"name": "Team", "crew_rank": 7, "cc_rp": 100}]}))
    assert main(["--gcc-response-json", str(p), "--reference-total", "100", "--format", "json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["network_requests_allowed"] is False
    assert result["gcc_supplied_response"]["rows"][0]["cc_rp"] == 100


def test_table_has_all_member_and_reference_values():
    result = {"at_utc": "2026-10-16T00:00:00+00:00",
              "member_response": make_member_report(_roster(), reference_total=220, reference_rank=257,
                                                     expected_members=3)}
    txt = _table(result)
    for expected in ("MR ORANGE", "150", "200", "220", "257", "-20", "GCC LEADERBOARD: NOT QUERIED"):
        assert expected in txt
