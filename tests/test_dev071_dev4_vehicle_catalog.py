"""Offline-only exact HUB CarData DBName resolution and privacy behavior."""
import json

import pytest

from csr2cdn.vehicle_catalog import VehicleCatalog, resolve_vehicle_report
from csr2cdn.crew_optional_data import CrewOptionalSnapshot, optional_report
from csr2cdn.service_models import OwnCrew, CrewMembers
from csr2cdn.crew_bulk_validation import bulk_report, main
from csr2cdn._service_reads import StandingRange


def car_data():
    return [
        {"DBName": "Abarth_500_2014", "Tier": 1, "Star": "G", "isEV": 0,
         "Vision": "LONG UNTRUSTED SECRET DESC", "SHIFT": "https://secret.example/key"},
        {"DBName": "Bristol_EV_2020", "Tier": 4, "Star": "P", "isEV": 1},
    ]


def wire():
    own = {"crew_uid": "SECRET_CREW", "members": 2}
    roster = {"crew_uid": "SECRET_CREW", "scores": [
        {"player_uid": "P1_PRIVATE", "name": "SECRET_NAME", "current_car": "Abarth_500_2014",
         "cc_contrib": 10, "garage_value": 1},
        {"player_uid": "P2_PRIVATE", "name": "SECRET_NAME_TWO", "current_car": "Not_Found",
         "cc_contrib": 11, "garage_value": 2},
    ]}
    common = {"scores": [{"crew_id": "SECRET_CREW", "name": "secret", "score": 21, "rank": 111}]}
    alternate = {"scores": [{"crew_id": "SECRET_CREW", "name": "secret", "score": 21, "rank": 111}]}
    return own, roster, common, alternate


def snapshot():
    own, roster, _, _ = wire()
    return CrewOptionalSnapshot.from_reads(OwnCrew.from_response(own),
                                           CrewMembers.from_response(own["crew_uid"], roster))


def test_source_backed_exact_match_and_record_fields():
    catalog = VehicleCatalog.from_car_data(car_data())
    assert catalog.size == 2
    record = catalog.match("Abarth_500_2014")
    assert (record.db_name, record.tier_candidate, record.star_marker_candidate, record.is_ev_candidate) == (
        "Abarth_500_2014", 1, "G", False)
    assert catalog.match("abarth_500_2014") is None
    assert catalog.match("Abarth_500_2014 ") is None
    assert catalog.match("missing") is None
    assert "SECRET DESC" not in repr(catalog) + repr(record)
    assert "secret.example" not in repr(record)


def test_privacy_by_default_and_explicit_member_opt_in():
    c = VehicleCatalog.from_car_data(car_data())
    report = resolve_vehicle_report(snapshot(), c)
    assert report["exact_dbname_matches"] == 1
    assert report["unresolved_rows"] == 1
    assert report["network_requests"] == 0
    for secret in ("SECRET_NAME", "SECRET_CREW", "P1_PRIVATE", "Abarth_500_2014", "LONG UNTRUSTED", "secret.example"):
        assert secret not in json.dumps(report)
    detailed = resolve_vehicle_report(snapshot(), c, show_members=True)
    assert detailed["member_catalogue_candidates"][0]["db_name"] == "Abarth_500_2014"
    assert detailed["member_catalogue_candidates"][1] == {"status": "unresolved"}
    assert detailed["member_catalogue_candidates"][0]["verified_in_game"] is False
    assert "SECRET_NAME" not in json.dumps(detailed)


def test_optional_report_catalogue_addition_does_not_change_existing_fields():
    snap = snapshot()
    baseline = optional_report(snap)
    upgraded = optional_report(snap, car_catalog=VehicleCatalog.from_car_data(car_data()))
    assert upgraded.pop("vehicle_catalogue")["catalog_records"] == 2
    assert upgraded == baseline
    with pytest.raises(TypeError, match="VehicleCatalog"):
        optional_report(snap, car_catalog=car_data())


def test_bulk_report_offline_catalogue_and_zero_network():
    result = bulk_report(*wire(), ranges=StandingRange(top=20, before=10, after=10, offset=0),
                         car_catalog=VehicleCatalog.from_car_data(car_data()))
    assert result["optional"]["vehicle_catalogue"]["exact_dbname_matches"] == 1
    assert result["network_requests_for_offline_decoder"] == 0
    assert "SECRET_NAME" not in json.dumps(result)


def test_empty_records_and_malformed_catalogue_fail_closed():
    assert VehicleCatalog.from_car_data([]).size == 0
    for data in ({}, [3], [{"DBName": ""}], [{"DBName": "a\nb"}],
                 [{"DBName": "x"}, {"DBName": "x"}],
                 [{"DBName": "x"}] * 10001):
        with pytest.raises(ValueError):
            VehicleCatalog.from_car_data(data)


def test_invalid_metadata_candidates_are_not_coerced():
    entry = VehicleCatalog.from_car_data([
        {"DBName": "A", "Tier": True, "Star": "x\x00", "isEV": "1"}
    ]).match("A")
    assert entry.tier_candidate is None
    assert entry.star_marker_candidate is None
    assert entry.is_ev_candidate is None
    assert VehicleCatalog.from_car_data([{"DBName": "B", "Tier": 0, "isEV": False}]).match("B").is_ev_candidate is False


def test_bulk_cli_local_car_catalogue(tmp_path, capsys):
    own, members, common, alternate = wire()
    paths = []
    for name, data in [("own", own), ("members", members), ("common", common),
                       ("experimental", alternate), ("cardata", car_data())]:
        path = tmp_path / (name + ".json")
        path.write_text(json.dumps(data), encoding="utf-8")
        paths.append(str(path))
    args = ["--own-json", paths[0], "--members-json", paths[1],
            "--gcc-common-json", paths[2], "--gcc-experimental-json", paths[3],
            "--car-catalog-json", paths[4]]
    assert main(args) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["optional"]["vehicle_catalogue"]["exact_dbname_matches"] == 1
    assert output["network_requests_for_offline_decoder"] == 0
    assert "SECRET_NAME" not in json.dumps(output)
    assert main(args + ["--show-members"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["optional"]["vehicle_catalogue"]["member_catalogue_candidates"][0]["db_name"] == "Abarth_500_2014"
    assert "P1_PRIVATE" not in json.dumps(output)


def test_dry_run_ignores_catalog_file_and_requires_no_network(tmp_path, capsys):
    assert main(["--car-catalog-json", str(tmp_path / "not-present.json")]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["network_requests"] == 0
