"""Dev19: no automatic speculative color/rim joins; no additional game reads."""
from dataclasses import FrozenInstanceError
import json
from unittest.mock import patch

import pytest

from csr2cdn import GameVisualLibrary, VisualGapDiagnostics, analyze_visual_gaps
from csr2cdn.crew_optional_data import CrewOptionalSnapshot
from csr2cdn.service_models import OwnCrew, CrewMembers
from csr2cdn.crew_bulk_validation import bulk_report, main
from csr2cdn._service_reads import StandingRange

SECRET = "PRIVATE_ACCOUNT_IDENTIFIER_SHOULD_NEVER_APPEAR"


def snapshot(rows=None):
    if rows is None:
        rows = [
            {"player_uid": SECRET, "name": "PRIVATE_PLAYER", "current_car": "MODEL_A",
             "car_paint_id": 2, "car_calliper_id": 9, "car_interior_id": 1,
             "car_wheel_name": "CUSTOM_WHEEL_PRIVATE", "car_decal_number_color_id": 2,
             "car_decal_number_shape_color_id": 17, "car_decal_number_zone_id": 2},
            {"player_uid": "private_2", "current_car": "MODEL_B",
             "car_paint_id": 10, "car_calliper_id": 9,
             "car_wheel_name": "14A", "car_decal_number_color_id": 2,
             "car_decal_number_shape_color_id": 17},
        ]
    own = OwnCrew.from_response({"crew_uid": SECRET, "members": len(rows)})
    roster = CrewMembers.from_response(SECRET, {"crew_uid": SECRET, "scores": rows})
    return CrewOptionalSnapshot.from_reads(own, roster)


def library():
    return GameVisualLibrary.from_manifest({"format": "csr2cdn.visual-code-library.v1", "records": [
        {"model_key": "*", "slot": "paint", "code": 2, "name": "RED_SOURCE", "source_library": "CarPaintLibrary"},
        {"model_key": "*", "slot": "color", "code": 2, "name": "COLOR_SOURCE", "source_library": "CarColorLibrary"},
        {"model_key": "*", "slot": "tuner_rim", "code": 1000001, "name": "14A", "source_library": "CarTunerStarsRimLibrary"},
        {"model_key": "*", "slot": "wheel", "code": "14A", "name": "SPECULATIVE_RIM", "source_library": "TestLibrary"},
    ]})


def test_count_and_reason_are_separate():
    gap = analyze_visual_gaps(snapshot(), library())
    assert isinstance(gap, VisualGapDiagnostics)
    assert gap.paint.present == 2 and gap.paint.resolved == 1 and gap.paint.library_id_missing == 1
    assert gap.calliper.library_id_missing == 2
    assert gap.wheel.join_unverified == 2 and gap.wheel.resolved == 0
    assert gap.wheel.tuner_rim_name_overlap == 1
    assert gap.decal_number_color.join_unverified == 2
    assert gap.decal_number_color.palette_id_overlap == 2
    assert gap.decal_number_shape_color.palette_id_overlap == 0
    assert gap.decal_number_zone.palette_id_overlap == 1
    assert gap.resolved_total == 1 and gap.present_total == 12 and gap.unresolved_total == 11
    assert gap.decal_flag.present == 0 and gap.decal_flag.unresolved == 0


def test_unverified_joins_not_auto_bound_even_with_manifest_candidates():
    gap = analyze_visual_gaps(snapshot(), library())
    assert gap.wheel.resolved == 0
    assert gap.decal_number_color.resolved == 0
    assert gap.decal_number_zone.resolved == 0
    assert gap.wheel.tuner_rim_name_overlap == 1
    assert gap.decal_number_color.palette_id_overlap == 2


def test_default_report_private_and_absent_numeric_ids():
    output = json.dumps(analyze_visual_gaps(snapshot(), library()).as_dict())
    for sensitive in (SECRET, "PRIVATE_PLAYER", "MODEL_A", "14A", "CUSTOM_WHEEL_PRIVATE", "RED_SOURCE", "SPECULATIVE_RIM"):
        assert sensitive not in output
    assert '"unresolved_numeric_ids"' not in output
    assert '"network_requests": 0' in output
    assert '"palette_overlap_is_not_join_proof": true' in output


def test_explicit_code_disclosure_only_numbers_without_member_association():
    gap = analyze_visual_gaps(snapshot(), library(), show_unmatched_ids=True)
    data = gap.as_dict()
    assert data["slots"]["paint"]["unresolved_numeric_ids"] == [{"id": 10, "occurrences": 1}]
    assert data["slots"]["decal_number_color"]["unresolved_numeric_ids"] == [{"id": 2, "occurrences": 2}]
    assert data["slots"]["wheel"]["unresolved_numeric_ids"] == []
    encoded = json.dumps(data)
    for secret in (SECRET, "CUSTOM_WHEEL_PRIVATE", "PRIVATE_PLAYER", "MODEL_B"):
        assert secret not in encoded


def test_numeric_zero_counts_as_real_id():
    gap = analyze_visual_gaps(snapshot([{"player_uid": "1", "current_car": "x",
                                         "car_paint_id": 0, "car_decal_number_zone_id": 0}]), library(),
                              show_unmatched_ids=True)
    assert gap.paint.present == 1 and gap.paint.library_id_missing == 1
    assert gap.decal_number_zone.join_unverified == 1
    assert gap.as_dict()["slots"]["paint"]["unresolved_numeric_ids"] == [{"id": 0, "occurrences": 1}]


@pytest.mark.parametrize("bad", ["yes", 1, None, [], {}])
def test_bad_disclosure_flag_rejected(bad):
    with pytest.raises(TypeError):
        analyze_visual_gaps(snapshot(), library(), show_unmatched_ids=bad)


def test_bad_input_types_and_roster_limit():
    with pytest.raises(TypeError):
        analyze_visual_gaps({}, library())
    with pytest.raises(TypeError):
        analyze_visual_gaps(snapshot(), {})
    roster = [{"player_uid": str(i), "current_car": "x"} for i in range(31)]
    with pytest.raises(ValueError):
        analyze_visual_gaps(snapshot(roster), library())


def test_immutable_structured_summary():
    gap = analyze_visual_gaps(snapshot(), library())
    with pytest.raises(FrozenInstanceError):
        gap.paint.resolved = 99
    assert gap.paint.unresolved == gap.paint.present - gap.paint.resolved
    with pytest.raises(AttributeError):
        _ = gap.user_identity
    assert 'PRIVATE' not in repr(gap)


def fixture():
    rows = [{"player_uid": SECRET, "current_car": "MODEL_A", "car_paint_id": 2,
             "car_decal_number_color_id": 2, "cc_contrib": 100}]
    own = {"crew_uid": SECRET, "members": 1}
    members = {"crew_uid": SECRET, "scores": rows}
    gcc = {"scores": [{"crew_id": SECRET, "rank": 10, "score": 100}]}
    return own, members, gcc, gcc


def test_bulk_diagnostics_without_game_requests():
    args = fixture()
    expected = bulk_report(*args, ranges=StandingRange(top=20,before=10,after=10,offset=0),game_visuals=library())
    assert expected["visual_gap_diagnostics"]["slots"]["paint"]["resolved"] == 1
    assert expected["visual_gap_diagnostics"]["slots"]["decal_number_color"]["join_unverified"] == 1
    assert "unresolved_numeric_ids" not in json.dumps(expected)


def test_bulk_explicit_code_opt_in_keeps_names_private():
    output = bulk_report(*fixture(), ranges=StandingRange(top=20,before=10,after=10,offset=0),
                         game_visuals=library(), show_unmatched_visual_ids=True)
    diag = output["visual_gap_diagnostics"]
    assert diag["slots"]["decal_number_color"]["unresolved_numeric_ids"] == [{"id":2,"occurrences":1}]
    assert SECRET not in json.dumps(output)


def test_cli_validates_disclosure_before_any_reads(capsys):
    with pytest.raises(SystemExit) as e:
        main(["--show-unmatched-visual-ids", "--execute"])
    assert e.value.code == 2
    msg = capsys.readouterr().err
    assert "requires a visual library" in msg
    assert SECRET not in msg


def test_cli_dry_run_remains_zero_network(capsys):
    assert main([]) == 0
    r = json.loads(capsys.readouterr().out)
    assert r["network_requests"] == 0
    assert r["planned_live_requests"] == 4


def test_no_new_implicit_file_or_network_calls():
    from pathlib import Path
    with patch.object(Path, 'write_text', side_effect=AssertionError("no disk write")):
        assert analyze_visual_gaps(snapshot(), library()).unresolved_total > 0
