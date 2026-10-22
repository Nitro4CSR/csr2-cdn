"""Dev22: evidence-gated TNR cohort probe, zero network unless explicitly opted in."""
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from csr2cdn import AssetDatabase
from csr2cdn.crew_optional_data import CrewOptionalSnapshot
from csr2cdn.game_labels import GameVisualLibrary
from csr2cdn.service_models import CrewMembers, OwnCrew
from csr2cdn.tnr_visual_probe import (
    TUNER_ASSETS, is_tnr_model, plan_tnr_assets,
    assess_tnr_snapshot, main,
)

HIDDEN = "SENSITIVE_CREW_OR_MEMBER_INFORMATION"


def fixture():
    own = {"crew_uid": HIDDEN, "members": 3}
    roster = {"crew_uid": HIDDEN, "scores": [
        {"player_uid": "SECRET_PLAYER_1", "name": "PRIVATE_NAME_1",
         "current_car": "Mazda_RX8TNR0_2008", "car_paint_id": 71,
         "car_interior_id": 101, "car_calliper_id": 222,
         "car_wheel_name": "PRIVATE_WHEEL_STRING", "car_decal_number_color_id": 2},
        {"player_uid": "SECRET_PLAYER_2", "name": "PRIVATE_NAME_2",
         "current_car": "Normal_Car_2024", "car_paint_id": 9,
         "car_interior_id": 101, "car_wheel_name": "SECRET_NORMAL_WHEEL"},
        {"player_uid": "SECRET_PLAYER_3", "name": "PRIVATE_NAME_3",
         "current_car": "Honda_CivicEGTNR2_1995", "car_paint_id": 71,
         "car_calliper_id": 123, "car_wheel_name": "SUPER_SECRET_TNR_WHEEL"},
    ]}
    db = AssetDatabase.from_json([{"version": "33695"}, [
        *({"code": code, "version": str(i+1), "sizes": {"ASTC": 1000+i}}
          for i, code in enumerate(TUNER_ASSETS)),
        {"code": "Mazda_RX8TNR0_2008_Wheel1A_3D", "version": "4", "sizes": {"ASTC": 50}},
        {"code": "Normal_Car_2024_Wheel1A_3D", "version": "5", "sizes": {"ASTC": 50}},
    ]])
    lib = GameVisualLibrary.from_manifest({"format":"csr2cdn.visual-code-library.v1", "records":[
        {"model_key": "*", "slot": "paint", "code": 9, "name": "NORMAL_PAINT",
         "source_library": "CarPaintLibrary"},
        {"model_key": "*", "slot": "interior", "code": 101, "name": "NORMAL_INTERIOR",
         "source_library": "CarInteriorLibrary"},
    ]})
    snap = CrewOptionalSnapshot.from_reads(
        OwnCrew.from_response(own), CrewMembers.from_response(HIDDEN, roster))
    return snap, db, lib, own, roster


def test_model_syntax_explicit_not_generic():
    assert is_tnr_model("Mazda_RX8TNR0_2008")
    assert is_tnr_model("Honda_CivicEGTNR2_1995")
    assert not is_tnr_model("Ferrari_TNR_branded")
    assert not is_tnr_model("TNRevival_2022")
    assert not is_tnr_model("Normal_Car_2024")
    assert not is_tnr_model(None)


def test_tuner_asset_plan_exact_versions_and_urls():
    _, db, _, _, _ = fixture()
    plan = plan_tnr_assets(db)
    assert plan.found == 9
    assert plan.entries[0].code == "CarTunerStarsPaintLibrary"
    assert plan.entries[0].url == "https://csr2.cdn.zynga.com/ANDROID/ASTC/CarTunerStarsPaintLibrary.ASTC.1"
    assert "native_source_schema_pending" in json.dumps(plan.as_dict())
    assert "standalone_rim_decoded_join_unverified" in json.dumps(plan.as_dict())


def test_absent_assets_have_no_fabricated_urls():
    _, _, _, _, _ = fixture()
    plan = plan_tnr_assets(AssetDatabase.from_json([{"version": "5"}, []]))
    assert plan.found == 0
    assert all(x.url is None for x in plan.entries)


def test_stale_or_invalid_asset_version_not_used():
    db = AssetDatabase.from_json([{"version": "5"}, [
        {"code": "CarTunerStarsPaintLibrary", "version": "../../private", "sizes": {"ASTC": 104}}
    ]])
    assert plan_tnr_assets(db).entries[0].url is None


def test_cohort_counts_no_speculative_join_and_no_private_output():
    snap, db, lib, _, _ = fixture()
    report = assess_tnr_snapshot(snap, db, lib)
    tnr = report["cohorts"]["tnr_model_syntax"]
    other = report["cohorts"]["other_or_unknown_model"]
    assert tnr["members"] == 2
    assert tnr["model_wheel_assets_found_members"] == 1
    assert tnr["model_wheel_assets_missing_members"] == 1
    assert other["members"] == 1
    assert other["model_wheel_assets_found_members"] == 1
    assert tnr["slot_coverage"]["paint"]["unresolved"] == 2
    assert other["slot_coverage"]["paint"]["resolved_in_standard_library"] == 1
    assert tnr["slot_coverage"]["interior"]["resolved_in_standard_library"] == 1
    assert tnr["slot_coverage"]["wheel"]["resolved_in_standard_library"] == 0
    assert tnr["slot_coverage"]["wheel"]["join_unverified"] is True
    text = json.dumps(report)
    for secret in (HIDDEN, "PRIVATE_NAME", "SECRET_PLAYER", "PRIVATE_WHEEL",
                   "SUPER_SECRET", "Mazda_RX8TNR", "Honda_CivicEGTNR", "Normal_Car", "NORMAL_PAINT"):
        assert secret not in text
    assert "\"unmatched_numeric_ids\":" not in text


def test_opt_in_ids_are_unassociated_and_wheels_suppressed():
    snap, db, lib, _, _ = fixture()
    out = assess_tnr_snapshot(snap, db, lib, show_unmatched_numeric_ids=True)
    report = json.dumps(out)
    assert out["cohorts"]["tnr_model_syntax"]["slot_coverage"]["paint"]["unmatched_numeric_ids"] == [
        {"id": 71, "occurrences": 2}]
    assert out["cohorts"]["tnr_model_syntax"]["slot_coverage"]["wheel"]["unmatched_numeric_ids"] == []
    for secret in ("PRIVATE_WHEEL", "SECRET_PLAYER", "Mazda_RX8TNR", HIDDEN):
        assert secret not in report


@pytest.mark.parametrize("bad", [1, 0, None, "yes", []])
def test_bad_opt_in_types_fail(bad):
    snap, db, lib, _, _ = fixture()
    with pytest.raises(TypeError):
        assess_tnr_snapshot(snap, db, lib, show_unmatched_numeric_ids=bad)


def test_dry_run_zero_requests(capsys):
    with patch("csr2cdn.tnr_visual_probe.CSR2Services", side_effect=AssertionError("network")):
        assert main([]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["network_requests"] == 0
    assert report["planned_live_requests"] == 2


def test_offline_replay_has_no_game_calls(tmp_path, capsys):
    snap, db, lib, own, roster = fixture()
    path = tmp_path / "database.json"
    path.write_text(db.dumps(), encoding="utf8")
    o = tmp_path / "own.json"; o.write_text(json.dumps(own), encoding="utf8")
    m = tmp_path / "roster.json"; m.write_text(json.dumps(roster), encoding="utf8")
    assert main(["--asset-database", str(path), "--own-json", str(o),
                 "--members-json", str(m), "--output", str(tmp_path / "report.json")]) == 0
    out = capsys.readouterr().out
    assert json.loads(out)["mode"] == "offline_replay"
    assert (tmp_path / "report.json").exists()
    assert HIDDEN not in out and "SECRET_PLAYER" not in out
    assert "PRIVATE_WHEEL" not in out


def test_live_call_count_two_and_hidden_player_id(tmp_path, monkeypatch, capsys):
    snap, db, lib, own, roster = fixture()
    path = tmp_path / "database.json"
    path.write_text(db.dumps(), encoding="utf8")
    calls = []
    class FakeService:
        def __init__(self, player_id, *, allow_network):
            assert allow_network and player_id == "PRIVATE_PLAYER_ID"
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def prepare_my_crew(self): return "own_contract"
        def prepare_crew_members(self, crew_id):
            assert crew_id == HIDDEN
            return "roster_contract"
        def _read(self, contract):
            calls.append(contract)
            return own if contract == "own_contract" else roster
    monkeypatch.setattr("csr2cdn.tnr_visual_probe.sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("csr2cdn.tnr_visual_probe.getpass.getpass", lambda prompt: "PRIVATE_PLAYER_ID")
    assert main(["--execute", "--asset-database", str(path)], services_factory=FakeService) == 0
    assert calls == ["own_contract", "roster_contract"]
    output = capsys.readouterr().out
    assert json.loads(output)["gameplay_read_count"] == 2
    for secret in (HIDDEN, "PRIVATE_PLAYER_ID", "SECRET_PLAYER", "PRIVATE_WHEEL"):
        assert secret not in output


def test_invalid_output_preflight_without_live_read(tmp_path, monkeypatch, capsys):
    existing = tmp_path / "report.json"; existing.write_text("already-here")
    with pytest.raises(SystemExit) as exc:
        main(["--execute", "--asset-database", "not-used", "--output", str(existing)])
    assert exc.value.code == 2
    assert existing.read_text() == "already-here"


def test_more_than_thirty_members_rejected():
    snap, db, lib, _, _ = fixture()
    from dataclasses import replace
    with pytest.raises(ValueError):
        assess_tnr_snapshot(replace(snap, members=snap.members * 11), db, lib)
