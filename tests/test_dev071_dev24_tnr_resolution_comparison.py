"""Dev24: offline counterfactual standard/TNR coverage and focused two-read gate."""
import json
from dataclasses import replace

import pytest

from csr2cdn import AssetDatabase
from csr2cdn.crew_optional_data import CrewOptionalSnapshot
from csr2cdn.game_labels import GameVisualLibrary, VisualCodeName
from csr2cdn.service_models import CrewMembers, OwnCrew
from csr2cdn.tnr_visual_probe import assess_tnr_resolution_comparison, main

HIDDEN = "NOT_FOR_REPORT"


def sample():
    own = {"crew_uid": HIDDEN, "members": 3}
    roster = {"crew_uid": HIDDEN, "scores": [
        {"player_uid": "ID_A", "name": "SECRET_NAME_A", "current_car": "Mazda_RX8TNR0_2008",
         "car_paint_id": 1000001, "car_interior_id": 1000001,
         "car_calliper_id": 1000001, "car_wheel_name": "SECRET_WHEEL_A"},
        {"player_uid": "ID_B", "name": "SECRET_NAME_B", "current_car": "Regular_Car_2022",
         "car_paint_id": 1000001, "car_interior_id": 7,
         "car_calliper_id": 8, "car_wheel_name": "SECRET_WHEEL_B"},
        {"player_uid": "ID_C", "name": "SECRET_NAME_C", "current_car": "Honda_CivicEGTNR2_1995",
         "car_paint_id": 9, "car_interior_id": 1000019,
         "car_calliper_id": 2000010, "car_wheel_name": "SECRET_WHEEL_C"},
    ]}
    snap = CrewOptionalSnapshot.from_reads(
        OwnCrew.from_response(own), CrewMembers.from_response(HIDDEN, roster))
    specs = (
        ("paint", "CarPaintLibrary", "CarTunerStarsPaintLibrary", 9, 1000001),
        ("interior", "CarInteriorLibrary", "CarTunerStarsInteriorLibrary", 7, 1000001),
        ("calliper", "CarCalliperLibrary", "CarTunerStarsCalliperLibrary", 8, 1000001),
    )
    records = []
    for slot, standard, tuner, standard_id, tuner_id in specs:
        records.append(VisualCodeName("*", slot, standard_id, "PRIVATE_STANDARD_LABEL", standard))
        records.append(VisualCodeName("*", slot, tuner_id, "PRIVATE_TNR_LABEL", tuner))
    # A model-restricted TNR value must not join to a different TNR car.
    records.append(VisualCodeName("Mazda_RX8TNR0_2008", "interior", 1000019,
                                  "PRIVATE_MODEL_LABEL", "CarTunerStarsInteriorLibrary"))
    visual = GameVisualLibrary(tuple(records))
    db = AssetDatabase.from_json([{"version": "33695"}, []])
    return snap, db, visual, own, roster


def test_exact_comparison_counters_and_privacy():
    snap, _, visual, _, _ = sample()
    result = assess_tnr_resolution_comparison(snap, visual)
    tnr = result["cohorts"]["tnr_model_syntax"]
    other = result["cohorts"]["other_or_unknown_model"]
    assert tnr["members"] == 2 and other["members"] == 1
    assert tnr["slots"]["paint"] == {
        "present": 2, "standard_matches": 1, "new_tnr_id_candidates": 1,
        "tnr_id_candidates_outside_tnr_models": 0,
        "ambiguous_cross_library_ids": 0, "still_unresolved": 0,
        "candidate_matches_after": 2,
    }
    assert tnr["slots"]["interior"]["new_tnr_id_candidates"] == 1
    assert tnr["slots"]["interior"]["still_unresolved"] == 1
    assert tnr["slots"]["calliper"]["new_tnr_id_candidates"] == 1
    assert tnr["slots"]["calliper"]["still_unresolved"] == 1
    assert other["slots"]["paint"]["tnr_id_candidates_outside_tnr_models"] == 1
    assert other["slots"]["paint"]["candidate_matches_after"] == 0
    assert result["totals"]["paint"]["new_tnr_id_candidates"] == 1
    assert result["ui_accuracy_verified"] is False
    data = json.dumps(result)
    for secret in (HIDDEN, "SECRET_NAME", "SECRET_WHEEL", "ID_A", "1000001",
                   "PRIVATE_TNR", "Regular_Car", "Mazda_RX8TNR"):
        assert secret not in data


def test_incomplete_source_sets_rejected():
    snap, _, visual, _, _ = sample()
    with pytest.raises(ValueError, match="six"):
        assess_tnr_resolution_comparison(snap, GameVisualLibrary(visual.records[:-2]))
    with pytest.raises(TypeError):
        assess_tnr_resolution_comparison(object(), visual)
    with pytest.raises(ValueError):
        assess_tnr_resolution_comparison(replace(snap, members=snap.members * 11), visual)


def test_cross_library_collision_not_counted_as_match():
    snap, _, visual, _, _ = sample()
    colliding = VisualCodeName("*", "paint", 9, "SECRET_TNR_LABEL",
                               "CarTunerStarsPaintLibrary")
    result = assess_tnr_resolution_comparison(snap, GameVisualLibrary(visual.records + (colliding,)))
    assert result["totals"]["paint"]["ambiguous_cross_library_ids"] == 1
    assert result["totals"]["paint"]["candidate_matches_after"] == 1


def test_probe_dry_run_is_zero_network_and_includes_flag(capsys):
    assert main(["--compare-standard-tnr"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["network_requests"] == 0
    assert result["standard_tnr_comparison_requested"] is True


def test_offline_replay_with_comparison(tmp_path, monkeypatch, capsys):
    snap, db, visual, own, roster = sample()
    db_path = tmp_path / "db.json"; db_path.write_text(db.dumps(), encoding="utf8")
    own_path = tmp_path / "own.json"; own_path.write_text(json.dumps(own), encoding="utf8")
    members_path = tmp_path / "roster.json"; members_path.write_text(json.dumps(roster), encoding="utf8")
    monkeypatch.setattr("csr2cdn.tnr_visual_probe.load_visual_libraries_unityfs", lambda paths: visual)
    args = ["--compare-standard-tnr", "--asset-database", str(db_path),
            "--own-json", str(own_path), "--members-json", str(members_path),
            "--visual-asset-bundle", "mocked-only", "--output", str(tmp_path / "safe.json")]
    assert main(args) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["mode"] == "offline_replay"
    assert out["gameplay_read_count"] == 0
    assert out["standard_tnr_comparison"]["totals"]["paint"]["new_tnr_id_candidates"] == 1
    assert json.loads((tmp_path / "safe.json").read_text()) == out


def test_missing_source_preflight_prevents_live_calls(tmp_path, monkeypatch, capsys):
    snap, db, visual, own, roster = sample()
    db_path = tmp_path / "db.json"; db_path.write_text(db.dumps())
    monkeypatch.setattr("csr2cdn.tnr_visual_probe.load_visual_libraries_unityfs",
                        lambda paths: GameVisualLibrary(visual.records[:1]))
    monkeypatch.setattr("csr2cdn.tnr_visual_probe.sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("csr2cdn.tnr_visual_probe.getpass.getpass",
                        lambda *args: pytest.fail("prompt happened before preflight"))
    class ForbiddenService:
        def __init__(self, *args, **kwargs):
            pytest.fail("network service constructed")
    code = main(["--execute", "--compare-standard-tnr", "--asset-database", str(db_path),
                 "--visual-asset-bundle", "mocked-only"], services_factory=ForbiddenService)
    assert code == 3
    assert json.loads(capsys.readouterr().out)["status"] == "tnr_probe_unavailable"


def test_mocked_live_two_reads_and_private_report(tmp_path, monkeypatch, capsys):
    snap, db, visual, own, roster = sample()
    db_path = tmp_path / "db.json"; db_path.write_text(db.dumps())
    monkeypatch.setattr("csr2cdn.tnr_visual_probe.load_visual_libraries_unityfs", lambda paths: visual)
    monkeypatch.setattr("csr2cdn.tnr_visual_probe.sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("csr2cdn.tnr_visual_probe.getpass.getpass", lambda *args: HIDDEN)
    calls = []
    class Fake:
        def __init__(self, player_id, *, allow_network):
            assert player_id == HIDDEN and allow_network
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def prepare_my_crew(self): return "own"
        def prepare_crew_members(self, crew_uid):
            assert crew_uid == HIDDEN
            return "roster"
        def _read(self, request):
            calls.append(request)
            return own if request == "own" else roster
    assert main(["--execute", "--compare-standard-tnr", "--asset-database", str(db_path),
                 "--visual-asset-bundle", "mocked-only"], services_factory=Fake) == 0
    out = capsys.readouterr().out
    assert json.loads(out)["gameplay_read_count"] == 2
    assert calls == ["own", "roster"]
    for secret in (HIDDEN, "SECRET_NAME", "SECRET_WHEEL", "Mazda_RX8TNR"):
        assert secret not in out
