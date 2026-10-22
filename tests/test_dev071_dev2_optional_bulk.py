"""Pure offline coverage for the optional data and one-round 0.7.1 batch probe."""
import json
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from csr2cdn._service_reads import StandingRange
from csr2cdn.crew_optional_data import (
    CrewOptionalSnapshot, CrewOptionalStats, CrewMemberVehicle, optional_report,
)
from csr2cdn.crew_bulk_validation import bulk_report, main
from csr2cdn.service_models import CrewMembers, OwnCrew


def inputs(count=2):
    own = {"crew_uid": "CREW_PRIVATE", "crew_name": "example", "members": count,
           "max_members": 30, "crew_rp": 987654, "crew_level": 25,
           "crew_level_base": 11600000, "crew_level_threshold": 11600000,
           "crew_garage_value": 1500, "crew_career_earning": 888,
           "crew_rr_point": 12, "total_invites": 0, "total_requests": 0,
           "crew_logo": {"id": 17, "colour": "red"}}
    members = {"crew_uid": "CREW_PRIVATE", "scores": [
        {"player_uid": f"PRIVATE_{i}", "name": f"PRIVATE_NAME_{i}",
         "role": "MEMBER", "cc_contrib": 20 + i, "garage_value": 100 + i,
         "career_earning": 500 + i, "cash_donated": 0,
         "collections_rank": 1, "season_pass_rp_boost": 30 if i == 0 else 0,
         "season_pass_premium_plus_pass_holder": i == 0,
         "last_log_in_time": 1720000000, "facebook_id": "FB_SECRET_123",
         "current_car": f"MODEL_CAR_{i}", "car_pp": 700 + i,
         "car_ep": 1000 + i, "car_elite_level": 5 + i,
         "car_am_milestone_level": 4, "car_restoration_status": None,
         "car_source": "mygarage", "car_tnr_setup": {"SECRET": "HIDDEN"},
         "car_gacha_config": {"caid": 0, "inid": 2, "livid": 3,
                              "lzsid": 4, "paid": 5, "whbn": "WHEELNAME",
                              "private": "DO_NOT_INCLUDE"}}
        for i in range(count)]}
    common = {"scores": [
        {"crew_id": "CREW_PRIVATE", "name": "PRIVATE_CREW_NAME", "rank": 345,
         "score": sum(20+i for i in range(count))},
        {"crew_id": "OTHER_ID", "name": "Other", "rank": 344, "score": 999},
    ]}
    expanded = {"scores": common["scores"] + [
        {"crew_id": "OTHER_ID_2", "name": "third crew", "rank": 343, "score": 1000}
    ]}
    return own, members, common, expanded


def _report(**opts):
    return bulk_report(*inputs(), ranges=StandingRange(top=20, before=10, after=10, offset=0), **opts)


def test_stat_and_vehicle_model_from_known_live_keys():
    own, roster, _, _ = inputs()
    snap = CrewOptionalSnapshot.from_reads(OwnCrew.from_response(own),
                                           CrewMembers.from_response("CREW_PRIVATE", roster))
    assert isinstance(snap.crew, CrewOptionalStats)
    assert snap.crew.crew_level == 25
    assert snap.crew.crew_rp_unverified == 987654
    assert snap.crew.members == 2
    assert snap.roster_count_matches_own_crew is True
    assert snap.identity_complete is True
    assert snap.members[0].stats.season_pass_rp_boost == 30
    assert snap.members[0].vehicle.model_key == "MODEL_CAR_0"
    assert snap.members[0].vehicle.gacha.caid == 0
    assert snap.members[0].vehicle.gacha.whbn == "WHEELNAME"
    assert snap.members[0].vehicle.tuning_setup_present is True
    assert snap.members[0].vehicle.tuning_setup_field_count == 1
    assert "PRIVATE_NAME" not in repr(snap)
    assert "PRIVATE_0" not in repr(snap)
    assert "DO_NOT_INCLUDE" not in repr(snap.members[0].vehicle)
    with pytest.raises(FrozenInstanceError):
        snap.crew.crew_level = 5


def test_partial_fields_do_not_infer_zero_or_coerce_booleans():
    car = CrewMemberVehicle.from_wire({"car_pp": True, "car_ep": -3,
                                       "car_elite_level": 2.2, "current_car": "ok"})
    assert car.pp is None and car.ep is None and car.elite_level is None
    assert car.model_key == "ok"
    assert CrewOptionalStats.from_own_crew(OwnCrew.from_response(
        {"crew_uid": "ABC", "crew_level": True})).crew_level is None


def test_malformed_roster_identity_and_count_are_reported():
    own, roster, _, _ = inputs()
    own["members"] = 3
    roster["scores"][1]["player_uid"] = "PRIVATE_0"
    snap = CrewOptionalSnapshot.from_reads(OwnCrew.from_response(own),
                                           CrewMembers.from_response("CREW_PRIVATE", roster))
    assert snap.identity_complete is False
    assert snap.roster_count_matches_own_crew is False


def test_default_report_has_no_private_values():
    report = _report()
    assert report["optional"]["member_rows"] == 2
    assert report["optional"]["member_stat_coverage"]["garage_value"] == 2
    assert report["optional"]["gacha_records"] == 2
    assert report["gcc"]["common"]["own_crew_exact_id_matches"] == 1
    assert report["gcc"]["experimental"]["rows"] == 3
    assert report["gcc"]["range_evidence"]["more_rows_than_common"] is True
    assert report["gcc"]["common_vs_experimental"]["matching_rank_and_score"] == 2
    assert report["gcc"]["range_evidence"]["range_honored_verified"] is False
    serialized = json.dumps(report)
    for hidden in ("PRIVATE_NAME", "PRIVATE_0", "CREW_PRIVATE", "FB_SECRET_123",
                   "DO_NOT_INCLUDE", "MODEL_CAR_0", "SECRET", "PRIVATE_CREW_NAME"):
        assert hidden not in serialized
    assert "987654" not in serialized


def test_explicit_aggregates_and_member_details_privacy():
    rpt = _report(show_stat_values=True)
    assert rpt["optional"]["crew_stat_candidates"]["crew_level"] == 25
    assert rpt["optional"]["member_aggregate_candidates"]["garage_value"]["sum"] == 201
    assert "PRIVATE_NAME_0" not in json.dumps(rpt)
    details = _report(show_members=True)
    text = json.dumps(details)
    assert "PRIVATE_NAME_0" in text
    assert "MODEL_CAR_0" in text
    assert "PRIVATE_0" not in text
    assert "FB_SECRET_123" not in text
    assert "DO_NOT_INCLUDE" not in text
    assert "SECRET" not in text


def test_explicit_gcc_entry_names_only_on_opt_in():
    assert "PRIVATE_CREW_NAME" not in json.dumps(_report())
    assert "PRIVATE_CREW_NAME" in json.dumps(_report(print_gcc_entries=True))


def test_incomplete_roster_prevents_sum_comparison():
    own, roster, a, b = inputs()
    own["members"] = 3
    timestamp = datetime(2026, 10, 17, tzinfo=timezone.utc)
    rpt = bulk_report(own, roster, a, b,
                      ranges=StandingRange(top=20, before=10, after=10, offset=0),
                      member_read_utc=timestamp, gcc_read_utc=timestamp)
    assert rpt["gcc"]["common"]["roster_gcc_comparable"] is False
    assert rpt["gcc"]["common"]["roster_gcc_delta"] is None


def test_good_roster_gcc_comparison():
    timestamp = datetime(2026, 10, 17, tzinfo=timezone.utc)
    rpt = _report(member_read_utc=timestamp, gcc_read_utc=timestamp)
    assert rpt["gcc"]["common"]["roster_gcc_comparable"] is True
    assert rpt["gcc"]["common"]["roster_gcc_delta"] == 0


def test_one_failed_experimental_schema_does_not_discard_stats():
    own, roster, a, _ = inputs()
    rpt = bulk_report(own, roster, a, {"scores": [{"score": 1}]},
                      ranges=StandingRange(top=20, before=10, after=10, offset=0))
    assert rpt["optional"]["member_rows"] == 2
    assert rpt["gcc"]["common"]["status"] == "decoded_common_gcc"
    assert rpt["gcc"]["experimental"]["status"] == "unrecognized_schema"
    assert rpt["feature_decisions"]["gcc_expanded_range"] == "investigate"


def test_default_cli_dry_run(capsys):
    assert main([]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["network_requests"] == 0
    assert data["planned_live_requests"] == 4


def test_cli_requires_interactive_terminal(capsys):
    with patch("csr2cdn.crew_bulk_validation.sys.stdin.isatty", return_value=False):
        assert main(["--execute"]) == 2
    assert "interactive_terminal_required" in capsys.readouterr().out


def test_cli_rejects_unbounded_parameters():
    with pytest.raises(SystemExit):
        main(["--top", "999999999"])


def test_offline_four_json_inputs(tmp_path, capsys):
    filenames = ("--own-json", "--members-json", "--gcc-common-json", "--gcc-experimental-json")
    cmd = []
    for i, (flag, response) in enumerate(zip(filenames, inputs())):
        p = tmp_path / f"sample_{i}.json"
        p.write_text(json.dumps(response), encoding="utf-8")
        cmd.extend([flag, str(p)])
    assert main(cmd) == 0
    rpt = json.loads(capsys.readouterr().out)
    assert rpt["optional"]["member_rows"] == 2
    assert rpt["gcc"]["experimental"]["rows"] == 3


def test_live_single_round_read_limit(monkeypatch, capsys):
    responses = inputs()
    events = []
    class MockServices:
        def __init__(self, player_id, allow_network=False):
            assert player_id == "test_player"
            assert allow_network
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def prepare_my_crew(self): return "own"
        def decode_my_crew(self, response): return OwnCrew.from_response(response)
        def prepare_crew_members(self, crew_uid):
            assert crew_uid == "CREW_PRIVATE"
            return "members"
        def _read(self, contract):
            events.append(contract)
            return {"own": responses[0], "members": responses[1]}[contract]
        def get_gcc_progress_response(self):
            events.append("gcc_common")
            return responses[2]
        def get_gcc_progress_range_response(self, ranges, exploratory):
            assert exploratory is True
            events.append("gcc_experimental")
            return responses[3]
    monkeypatch.setattr("csr2cdn.crew_bulk_validation.getpass.getpass", lambda *_: "test_player")
    monkeypatch.setattr("csr2cdn.crew_bulk_validation.sys.stdin.isatty", lambda: True)
    assert main(["--execute"], services_factory=MockServices) == 0
    assert events == ["own", "members", "gcc_common", "gcc_experimental"]
    text = capsys.readouterr().out
    assert "PRIVATE_NAME_0" not in text
    assert "test_player" not in text
    assert '"rows": 3' in text


def test_garage_aggregate_exact_match_without_exposing_amounts():
    own, roster, a, b = inputs()
    own["crew_garage_value"] = 201
    result = bulk_report(own, roster, a, b,
                         ranges=StandingRange(top=20, before=10, after=10, offset=0))
    assert result["optional"]["garage_aggregation"] == {"comparable": True, "equal": True}
    assert "201" not in json.dumps(result["optional"]["garage_aggregation"])
    result = bulk_report(own, roster, a, b, ranges=StandingRange(top=20, before=10, after=10, offset=0), show_stat_values=True)
    assert result["optional"]["garage_aggregation"]["delta"] == 0


def test_garage_aggregate_refuses_partial_roster():
    own, roster, a, b = inputs()
    own["crew_garage_value"] = 201
    own["members"] = 3
    result = bulk_report(own, roster, a, b,
                         ranges=StandingRange(top=20, before=10, after=10, offset=0))
    assert result["optional"]["garage_aggregation"]["comparable"] is False
    assert result["optional"]["garage_aggregation"]["equal"] is None
