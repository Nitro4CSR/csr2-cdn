"""Dev27 regressions: non-atomic comparison gates and clock-stable Showdown."""
import json
from datetime import datetime, timezone
from pathlib import Path

from csr2cdn.crew_rp_verification import (
    compare_sequential_crew_reads, make_gcc_progress_report, make_member_report,
    verify, _table, main,
)
from csr2cdn.service_models import CrewMembers, OwnCrew


def roster():
    return CrewMembers.from_response("ours", {"crewMembers": [
        {"player_uid": "secret_member1", "nickname": "First", "cc_contrib": 100, "player_rp": 900},
        {"player_uid": "secret_member2", "nickname": "Second", "cc_contrib": "200", "player_rp": 3000},
    ]})


def board():
    return {"scores": [
        {"crew_id": "secret_crew_own", "name": "Crew A", "rank": 253, "score": 303, "logo": {}},
        {"crew_id": "secret_crew_other", "name": "Crew B", "rank": 254, "score": 299},
    ]}


def test_complete_sequential_comparison_only_reports_candidates_not_season_proof():
    m = make_member_report(roster(), expected_members=2)
    b = make_gcc_progress_report(board(), own_crew_uid="secret_crew_own")
    r = compare_sequential_crew_reads(m, b, member_read_utc="2026-10-16T10:00:00+00:00",
                                      gcc_read_utc="2026-10-16T10:00:02+00:00")
    assert r["status"] == "sequential_read_candidates_compared"
    assert r["member_cc_contrib_sum"] == 300
    assert r["matched_gcc_score"] == 303
    assert r["member_sum_minus_gcc_score"] == -3
    assert r["absolute_difference"] == 3
    assert r["not_an_atomic_snapshot"] is True
    assert r["score_semantics_verified"] is False
    assert r["season_scope_verified"] is False
    assert "secret_member" not in json.dumps(r)
    assert "secret_crew" not in json.dumps(r)


def test_missing_own_match_fails_closed_even_if_score_coincides():
    m = make_member_report(roster())
    b = make_gcc_progress_report(board(), own_crew_uid="wrong_crew")
    r = compare_sequential_crew_reads(m, b, member_read_utc="A", gcc_read_utc="B")
    assert r["status"] == "comparison_unavailable"
    assert r["member_sum_minus_gcc_score"] is None
    assert r["exact_own_crew_id_match"] is False


def test_missing_and_fallback_only_rows_fail_closed():
    incomplete = CrewMembers.from_response("ours", {"crewMembers": [
        {"player_uid": "m1", "cc_contrib": 5}, {"player_uid": "m2", "score": 6},
    ]})
    r = compare_sequential_crew_reads(make_member_report(incomplete),
        make_gcc_progress_report(board(), own_crew_uid="secret_crew_own"),
        member_read_utc="A", gcc_read_utc="B")
    assert r["status"] == "comparison_unavailable"
    assert r["complete_cc_contrib_roster"] is False
    assert r["member_sum_minus_gcc_score"] is None


def test_duplicate_member_identity_fails_closed():
    duplicates = CrewMembers.from_response("ours", {"crewMembers": [
        {"player_uid": "m1", "cc_contrib": 5}, {"player_uid": "m1", "cc_contrib": 6},
    ]})
    r = compare_sequential_crew_reads(make_member_report(duplicates),
        make_gcc_progress_report(board(), own_crew_uid="secret_crew_own"),
        member_read_utc="A", gcc_read_utc="B")
    assert r["status"] == "comparison_unavailable"
    assert r["member_sum_minus_gcc_score"] is None


def test_only_existing_three_read_operations_are_used_and_printing_is_explicit():
    calls = []
    class Service:
        def __init__(self, *args, **kwargs): calls.append(("init", kwargs["allow_network"]))
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def get_my_crew(self):
            calls.append("own")
            return OwnCrew("secret_crew_own")
        def get_crew_members(self):
            calls.append("roster")
            return roster()
        def get_gcc_progress_response(self):
            calls.append("gcc")
            return board()
    report = verify(player_id="private_PlayerID", execute=True, gcc_live=True,
                    expected_members=2, services_factory=Service,
                    gcc_print_score_candidates=True)
    assert calls == [("init", True), "own", "roster", "gcc"]
    comparison = report["sequential_roster_gcc_comparison"]
    assert comparison["member_sum_minus_gcc_score"] == -3
    assert comparison["member_read_utc"] <= comparison["gcc_read_utc"]
    assert report["gcc_live_response"]["matched_own_crew_records"] == 1
    printed = _table(report)
    assert "SEQUENTIAL ROSTER" in printed
    assert "sum minus score: -3" in printed
    assert "NOT ATOMIC" in printed
    assert "PRIVATE" not in printed
    assert "private_PlayerID" not in json.dumps(report)
    assert "secret_member1" not in json.dumps(report)
    assert "secret_crew_own" not in json.dumps(report)


def test_gcc_only_suppresses_roster_comparison():
    class Service:
        def __init__(self, *args, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def get_my_crew(self): return OwnCrew("secret_crew_own")
        def get_crew_members(self): raise AssertionError("roster suppressed")
        def get_gcc_progress_response(self): return board()
    r = verify(player_id="P", execute=True, gcc_only=True, gcc_live=True,
               services_factory=Service)
    assert "sequential_roster_gcc_comparison" not in r
    assert "SEQUENTIAL ROSTER" not in _table(r)


def test_dry_run_still_never_contacts_server(capsys):
    assert main([]) == 0
    assert json.loads(capsys.readouterr().out)["network_requests"] == 0


def test_expected_roster_size_mismatch_does_not_count_as_complete():
    r = compare_sequential_crew_reads(
        make_member_report(roster(), expected_members=29),
        make_gcc_progress_report(board(), own_crew_uid="secret_crew_own"),
        member_read_utc="A", gcc_read_utc="B")
    assert r["status"] == "comparison_unavailable"
    assert r["complete_cc_contrib_roster"] is False
    assert r["member_sum_minus_gcc_score"] is None
