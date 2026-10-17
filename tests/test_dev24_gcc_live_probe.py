"""Dev24: GCC progress is one explicit, allowlisted, experimental read."""
import json
from collections import OrderedDict
from dataclasses import replace

import pytest

from csr2cdn._service_reads import (
    GCC_METADATA_DEFAULT_PREFIX, ReadContract, ReadContractError,
    gcc_progress_contract, prepare_read_contract,
)
from csr2cdn.crew_rp_verification import (
    gcc_safe_schema, make_member_report, main, verify, _table,
)
from csr2cdn.service_models import CrewMembers, OwnCrew
from csr2cdn.services import CSR2Services


def test_native_gcc_progress_exact_route_order_and_classification():
    contract = gcc_progress_contract()
    assert contract.route == "leaderboard/crew-champs-v2/viewcrew"
    assert contract.request_type == 3
    assert contract.params == OrderedDict([
        ("app_ver", "6.8.0"), ("top", 10), ("after", 5),
        ("before", 5), ("offset", 0),
    ])
    assert contract.route == GCC_METADATA_DEFAULT_PREFIX + "viewcrew"
    assert CSR2Services("123", allow_network=False).prepare_gcc_progress() == contract


def test_gcc_progress_rejects_route_fabrication_and_changed_ranges():
    with pytest.raises(ReadContractError):
        gcc_progress_contract(endpoint_prefix="leaderboard/other/")
    with pytest.raises(ReadContractError):
        gcc_progress_contract(app_version="not a game version")

    # Attacker-mutated requests must not be signed or emitted.
    for contract in (
        replace(gcc_progress_contract(), route="leaderboard/crew-champs-v2/viewmax"),
        replace(gcc_progress_contract(), request_type=5),
        replace(gcc_progress_contract(), params={"app_ver": "6.8.0", "top": 100,
                                                   "after": 5, "before": 5, "offset": 0}),
        replace(gcc_progress_contract(), params={"top": 10, "app_ver": "6.8.0",
                                                   "after": 5, "before": 5, "offset": 0}),
    ):
        # An invalid session is sufficient here; validator must reject
        # malformed routes before it inspects credentials.
        with pytest.raises(ReadContractError):
            prepare_read_contract(None, contract)


def test_typed_member_contribution_only_from_cc_contrib_not_score_or_profile():
    roster = CrewMembers.from_response("crew", {"crewMembers": [
        {"player_uid": "m1", "cc_contrib": "111", "player_rp": 900000},
        {"player_uid": "m2", "score": 222, "player_rp": 900000},
        {"player_uid": "m3", "score": 333, "cc_contrib": None},
        {"player_uid": "m4", "cc_contrib": 0, "player_rp": 100},
    ]})
    a, b, c, d = roster.members
    assert a.season_crew_rp == 111
    assert b.season_crew_rp is None and b.season_crew_rp_candidate == 222
    assert c.season_crew_rp is None and c.season_crew_rp_candidate is None
    assert d.season_crew_rp == 0
    assert all(m.crew_rp is None for m in roster.members)


def test_gcc_live_only_runs_one_board_read_and_never_roster_read():
    calls = []

    class FakeSvc:
        def __init__(self, *args, **kwargs):
            calls.append(("init", kwargs["allow_network"]))
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def get_my_crew(self):
            calls.append("crews/checkUserCrew")
            return OwnCrew("ours")
        def get_crew_members(self):
            raise AssertionError("roster read must be skipped")
        def get_gcc_progress_response(self):
            calls.append("gcc-progress-read")
            return {"results": [
                {"uid": "ours", "name": "Our Crew", "cc_rp": 37463129,
                 "crew_rank": 257, "rp": 123456789},
                {"uid": "other", "name": "Other", "cc_rp": 50000000,
                 "crew_rank": 256},
            ]}

    report = verify(player_id="PRIVATE_ID", execute=True, gcc_live=True,
                    gcc_only=True, services_factory=FakeSvc,
                    reference_total=37448821, reference_rank=257)
    assert calls == [("init", True), "crews/checkUserCrew", "gcc-progress-read"]
    assert "member_response" not in report
    gcc = report["gcc_live_response"]
    assert gcc["result_count"] == 2
    assert gcc["own_crew_cc_rp_minus_ui_total"] == 14308
    assert gcc["own_crew_rank_matches_ui"] is True
    assert gcc["active_season_verified"] is False
    out = _table(report)
    assert "LIVE experimental progress" in out
    assert "37,463,129" in out
    assert "Other" in out
    assert "PRIVATE_ID" not in json.dumps(report)
    assert '"uid"' not in json.dumps(report)


def test_gcc_live_unknown_envelope_prints_safe_structural_fallback():
    class FakeSvc:
        def __init__(self, *args, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def get_my_crew(self): return OwnCrew("ours")
        def get_gcc_progress_response(self):
            return {"accessToken": "PRIVATE", "responseData": {"data": {"results": [
                {"uid": "private_member", "cc_rp": 999, "nickname": "PRIVATE"}]}}}
    r = verify(player_id="123", execute=True, gcc_live=True, gcc_only=True,
               services_factory=FakeSvc)
    body = json.dumps(r)
    assert "PRIVATE" not in body
    assert "private_member" not in body
    assert r["gcc_live_response"]["status"] == "unrecognized_native_gcc_schema"
    assert "recognized_fields" in body
    assert "responseData" in body


def test_gcc_live_requires_explicit_execution(capsys):
    with pytest.raises(SystemExit) as ex:
        main(["--gcc-live"])
    assert ex.value.code == 2
    with pytest.raises(SystemExit) as ex:
        main(["--gcc-only"])
    assert ex.value.code == 2
    assert main([]) == 0
    assert json.loads(capsys.readouterr().out)["network_requests"] == 0


def test_default_no_gcc_network_even_with_previous_crew_report():
    roster = CrewMembers.from_response("crew", {"crewMembers": [
        {"player_uid": "x", "name": "Example", "cc_contrib": 200}]})
    report = make_member_report(roster)
    assert report["sum_of_available_member_candidates"] == 200
    assert report["roster_count"] == 1


def test_safe_schema_does_not_dump_unknown_keys_or_values():
    r = gcc_safe_schema({"unknown": "TOKEN", "results": [
        {"uid": "secret", "cc_rp": 10}, {"uid": "secret2", "cc_rp": 20}]})
    s = json.dumps(r)
    assert "secret" not in s and "TOKEN" not in s and "unknown" not in s
    assert r["recognized_nested_fields"]["results"]["cc_rp_rows"] == 2
