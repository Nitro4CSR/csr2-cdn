"""0.7.1.dev3: observed read-only cosmetic fields, privacy and isolated batch failures."""
import json
from unittest.mock import patch

import pytest

from csr2cdn._service_reads import StandingRange
from csr2cdn.crew_bulk_validation import bulk_report, main
from csr2cdn.crew_optional_data import (
    CrewPresentation, CrewVehicleAppearance, CrewOptionalSnapshot,
    CrewTournamentShape, CrewEmblem, CrewMemberVehicle, optional_report,
)
from csr2cdn.service_models import OwnCrew, CrewMembers
from csr2cdn.services import ServiceHTTPError


RANGE = StandingRange(top=20, before=10, after=10, offset=0)


def data():
    own = {"crew_uid": "SECRET_CREW_ID", "crew_name": "Crew", "members": 1,
           "crew_logo": {"id": 27, "colour": "FFAABB", "hidden_token": "LOGO_SECRET"},
           "crew_motto": "OUR PRIVATE MOTTO", "crew_language": "en-US",
           "tournament": {"events": {"secret_event": {"auth": "SECRET_EVENT"}},
                          "extra": {}, "meta": {"TOKEN_PRIVATE": "TOKEN_SECRET"}},
           "crew_garage_value": 100}
    roster = {"crew_uid": "SECRET_CREW_ID", "scores": [
        {"player_uid": "PRIVATE_PLAYER", "name": "PRIVATE_NAME", "role": "MEMBER",
         "cc_contrib": 17, "garage_value": 100,
         "car_calliper_id": 0, "car_interior_id": 1, "car_livery_id": 2,
         "car_liveryZonesSet_id": 3, "car_paint_id": 4,
         "car_wheel_name": "SPECIAL WHEEL", "car_decal_flag_id": 5,
         "car_decal_number_id": 6, "car_decal_number_color_id": 7,
         "car_decal_number_shape_color_id": 8, "car_decal_number_zone_id": 9,
         "car_decal_numberplate_style_id": 10,
         "car_decal_playername_state": 11, "car_decal_crewname_state": 12,
         "license_plate_text": "PRIVATE_PLATE_1", "facebook_id": "SECRET_SOCIAL_ID",
         "last_log_in_time": 1660000000,
         "car_tnr_setup": {"auth_secret": "TOP_SECRET_SETUP"},
         "car_gacha_config": {"caid": 0, "private": "GACHA_SECRET"}}]}
    common = {"scores": [{"crew_id": "SECRET_CREW_ID", "name": "SECRET_CREW_NAME",
                          "rank": 25, "score": 17}]}
    experimental = {"scores": [{"crew_id": "SECRET_CREW_ID", "name": "SECRET_CREW_NAME",
                                "rank": 25, "score": 17},
                               {"crew_id": "ANOTHER", "name": "ANOTHER_CREW", "rank": 23, "score": 22}]}
    return own, roster, common, experimental


def snapshot():
    own, roster, _, _ = data()
    return CrewOptionalSnapshot.from_reads(OwnCrew.from_response(own),
                                           CrewMembers.from_response(own["crew_uid"], roster))


def test_presentation_and_tournament_are_shape_only_by_default():
    snap = snapshot()
    assert snap.presentation.logo.emblem_id == 27
    assert snap.presentation.logo.colour == "FFAABB"
    t = snap.presentation.tournament
    assert isinstance(t, CrewTournamentShape)
    assert t.present and t.events_present and t.extra_present and t.meta_present
    assert (t.events_keys, t.extra_keys, t.meta_keys) == (1, 0, 1)
    report = optional_report(snap)
    assert report["crew_presentation_presence"] == {
        "logo_id": True, "logo_colour": True, "motto": True, "language": True}
    assert report["tournament_shape"]["meta_keys"] == 1
    rendered = json.dumps(report)
    for secret in ("TOKEN_PRIVATE", "TOKEN_SECRET", "SECRET_EVENT", "OUR PRIVATE MOTTO",
                   "SECRET_CREW_ID", "FFAABB", "SPECIAL WHEEL"):
        assert secret not in rendered
    assert "OUR PRIVATE MOTTO" not in repr(snap.presentation)
    assert "FFAABB" not in repr(snap.presentation.logo)
    assert "SECRET_EVENT" not in repr(snap)


def test_vehicle_appearance_exact_fields_and_zero_id():
    snap = snapshot()
    cosmetic = snap.members[0].vehicle.appearance
    assert isinstance(cosmetic, CrewVehicleAppearance)
    assert cosmetic.calliper_id == 0
    assert cosmetic.livery_zones_set_id == 3
    assert cosmetic.decal_numberplate_style_id == 10
    assert cosmetic.decal_crewname_state == 12
    assert cosmetic.wheel_name == "SPECIAL WHEEL"
    assert "SPECIAL WHEEL" not in repr(cosmetic)
    report = optional_report(snap)
    assert report["vehicle_appearance_coverage"]["calliper_id"] == 1
    assert report["vehicle_appearance_coverage"]["wheel_name"] == 1
    assert report["vehicle_appearance_coverage"]["decal_crewname_state"] == 1
    assert "PRIVATE_PLATE_1" not in json.dumps(report)


def test_explicit_opt_in_prints_cosmetics_but_no_opaque_tokens_or_social_ids():
    """Opt-in printing covers in-game values; tokens and social IDs never.

    Policy change 2026-10-21, by the maintainer: in-game player IDs, crew IDs
    and license plate text are fine to print. They are values a player reads
    off the roster screen. What stays withheld unconditionally is a different
    category: opaque auth/token fields (`hidden_token`, `auth`, `auth_secret`,
    and anything unrecognised) and the real-world Facebook account ID.
    """
    snap = snapshot()
    report = optional_report(snap, show_members=True, show_values=True)
    assert report["crew_presentation_candidates"]["logo_id"] == 27
    assert report["crew_presentation_candidates"]["motto"] == "OUR PRIVATE MOTTO"
    assert report["member_candidates"][0]["appearance"]["wheel_name"] == "SPECIAL WHEEL"
    rendered = json.dumps(report)
    for secret in ("SECRET_SOCIAL_ID", "LOGO_SECRET", "TOKEN_PRIVATE", "TOKEN_SECRET",
                   "SECRET_EVENT", "GACHA_SECRET", "TOP_SECRET_SETUP"):
        assert secret not in rendered, secret


@pytest.mark.parametrize("field,value", [
    ("car_paint_id", -2), ("car_paint_id", True), ("car_paint_id", 2.1),
    ("car_paint_id", "not-a-number"), ("car_wheel_name", "x" * 181),
])
def test_invalid_appearance_field_omitted(field, value):
    cosmetic = CrewVehicleAppearance.from_wire({field: value})
    assert cosmetic is None


def test_null_or_opaque_nested_data_is_not_decoded():
    assert CrewVehicleAppearance.from_wire({"license_plate_text": "private"}) is None
    assert CrewEmblem.from_mapping({"id": False, "colour": 999}) is None
    assert CrewTournamentShape.from_mapping({"events": ["secret"]}).events_present is False
    assert CrewMemberVehicle.from_wire({"car_tnr_setup": "invalid"}).tuning_setup_present is False
    assert CrewTournamentShape.from_mapping(None).present is False
    assert CrewVehicleAppearance.from_wire({"car_calliper_id": 0}).calliper_id == 0


def test_batch_common_failure_keeps_optional_and_experimental():
    args = data()
    result = bulk_report(args[0], args[1], None, args[3], ranges=RANGE,
                         read_errors={"common": {"status": "http_error", "status_code": 502, "details": "suppressed"}})
    assert result["status"] == "bulk_partial_read"
    assert result["gcc"]["common"]["status_code"] == 502
    assert result["gcc"]["experimental"]["rows"] == 2
    assert result["optional"]["vehicle_appearance_coverage"]["paint_id"] == 1
    assert result["feature_decisions"]["vehicle_appearance"] == "candidate_only"
    assert result["feature_decisions"]["tournament_shape"] == "candidate_only"
    assert "common_vs_experimental" not in result["gcc"]


def test_batch_experimental_failure_keeps_optional_and_common():
    args = data()
    result = bulk_report(args[0], args[1], args[2], None, ranges=RANGE,
                         read_errors={"experimental": {"status": "read_unavailable", "details": "suppressed"}})
    assert result["status"] == "bulk_partial_read"
    assert result["gcc"]["common"]["rows"] == 1
    assert result["gcc"]["experimental"]["status"] == "read_unavailable"
    assert result["feature_decisions"]["gcc_expanded_range"] == "investigate"


@pytest.mark.parametrize("failed", ["common", "experimental"])
def test_live_http_failure_captures_other_read_and_returns_nonzero(monkeypatch, capsys, failed):
    own, roster, common, experimental = data()
    events = []

    class FakeService:
        def __init__(self, player_id, allow_network=False):
            assert player_id == "my_id" and allow_network
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def prepare_my_crew(self): return "own"
        def prepare_crew_members(self, crew_uid): return "roster"
        def decode_my_crew(self, reply): return OwnCrew.from_response(reply)
        def _read(self, contract):
            events.append(contract)
            return {"own": own, "roster": roster}[contract]
        def get_gcc_progress_response(self):
            events.append("common")
            if failed == "common":
                raise ServiceHTTPError(503, "PRIVATE_TOKEN=http_secret")
            return common
        def get_gcc_progress_range_response(self, ranges, exploratory):
            events.append("experimental")
            assert exploratory
            if failed == "experimental":
                raise ServiceHTTPError(429, "PRIVATE_TOKEN=http_secret")
            return experimental

    monkeypatch.setattr("csr2cdn.crew_bulk_validation.sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("csr2cdn.crew_bulk_validation.getpass.getpass", lambda *_: "my_id")
    assert main(["--execute"], services_factory=FakeService) == 4
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "bulk_partial_read"
    assert result["optional"]["member_rows"] == 1
    assert events == ["own", "roster", "common", "experimental"]
    printed = json.dumps(result)
    for secret in ("PRIVATE_TOKEN", "http_secret", "PRIVATE_PLAYER", "PRIVATE_NAME", "SECRET_CREW_ID"):
        assert secret not in printed


def test_dry_run_zero_network_still():
    with patch("csr2cdn.crew_bulk_validation.sys.stdin.isatty", return_value=False):
        assert main([]) == 0
