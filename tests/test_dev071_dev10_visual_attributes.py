"""Dev10: offline attribute-first visual naming; synthetic evidence only."""
from dataclasses import FrozenInstanceError
import json

import pytest

from csr2cdn import (CarNameStyle, CrewMemberVehicle, CrewOptionalSnapshot,
                     CrewVehicleAppearance, CrewVehicleVisuals, CrewVisualSelection,
                     GameCarTranslations, GameVisualLibrary)
from csr2cdn.game_labels import game_label_report
from csr2cdn.crew_optional_data import optional_report
from csr2cdn.service_models import OwnCrew, CrewMembers


def translations():
    return GameCarTranslations.from_manifest({
        "format": "csr2cdn.car-translations.v1",
        "records": [
            {"model_key": "Car_A", "SHORT": "A", "MEDIUM": "Car A", "LONG": "Maker Model A"},
            {"model_key": "Car_B", "SHORT": "B", "LONG": "Maker Model B"},
        ]})


def visuals():
    return GameVisualLibrary.from_manifest({
        "format": "csr2cdn.visual-code-library.v1",
        "records": [
            {"model_key": "Car_A", "slot": "paint", "code": 0,
             "name": "PRIVATE_PEARL", "source_library": "CarLiveriesMatrix",
             "metadata_hash": "a" * 32},
            {"model_key": "Car_A", "slot": "wheel", "code": "WHEEL_SPEC_A",
             "name": "PRIVATE_SPOKE", "source_library": "CarAftermarketCustomisations"},
            {"model_key": "Car_B", "slot": "paint", "code": 0,
             "name": "B PAINT", "source_library": "CarLiveriesMatrix"},
        ]})


def wire_vehicle(**other):
    base = {"current_car": "Car_A", "car_paint_id": 0,
            "car_wheel_name": "WHEEL_SPEC_A", "car_decal_flag_id": 5,
            "car_pp": 550}
    base.update(other)
    return CrewMemberVehicle.from_wire(base)


def snapshot():
    own = OwnCrew.from_response({"crew_uid": "PRIVATE_CREW", "members": 2})
    roster = CrewMembers.from_response("PRIVATE_CREW", {
        "crew_uid": "PRIVATE_CREW", "scores": [
            {"player_uid": "PRIVATE_1", "name": "PRIVATE_PERSON_ONE",
             "current_car": "Car_A", "car_paint_id": 0,
             "car_wheel_name": "WHEEL_SPEC_A", "car_decal_flag_id": 5,
             "cc_contrib": 50},
            {"player_uid": "PRIVATE_2", "name": "PRIVATE_PERSON_TWO",
             "current_car": "Car_B", "car_paint_id": 0,
             "cc_contrib": 100},
        ]})
    return CrewOptionalSnapshot.from_reads(own, roster)


def test_visuals_are_explicitly_bound_and_keep_raw_values():
    source = wire_vehicle()
    assert source.visuals is None
    bound = source.with_visuals(visuals())
    assert source.visuals is None
    assert bound is not source
    assert bound.appearance.paint_id == 0  # zero is a real ID
    assert bound.visuals.paint.code == 0
    assert bound.visuals.paint.name == "PRIVATE_PEARL"
    assert bound.visuals.paint.source_library == "CarLiveriesMatrix"
    assert bound.visuals.paint.source_hash == "a" * 32
    assert bound.visuals.wheel.code == "WHEEL_SPEC_A"
    assert bound.visuals.wheel.name == "PRIVATE_SPOKE"
    assert bound.visuals.decal_flag.code == 5
    assert bound.visuals.decal_flag.name is None
    assert bound.visuals.decal_flag.source_hash is None
    assert bound.visuals.paint.resolved
    assert not bound.visuals.decal_flag.resolved
    assert bound.visuals.present_count == 3
    assert bound.visuals.resolved_count == 2
    with pytest.raises(FrozenInstanceError):
        bound.visuals.paint.name = "BAD"


def test_unseen_model_never_inherits_another_models_visual_code():
    source = wire_vehicle(current_car="NotCar", car_wheel_name="UNKNOWN")
    bound = source.with_visuals(visuals())
    assert bound.visuals.paint is not None
    assert bound.visuals.paint.name is None
    assert bound.visuals.wheel.name is None
    assert bound.visuals.decal_flag.name is None


def test_wrong_code_type_or_different_numeric_code_is_not_a_match():
    source = wire_vehicle(car_paint_id=1, car_wheel_name="0")
    assert source.with_visuals(visuals()).visuals.paint.name is None
    assert source.with_visuals(visuals()).visuals.wheel.name is None


def test_all_missing_appearance_uses_empty_explicit_binding():
    car = CrewMemberVehicle.from_wire({"current_car": "Car_A"})
    bound = car.with_visuals(visuals())
    assert isinstance(bound.visuals, CrewVehicleVisuals)
    assert bound.visuals.present_count == 0
    assert bound.visuals.paint is None
    assert bound.appearance is None


def test_invalid_library_is_rejected():
    with pytest.raises(TypeError):
        wire_vehicle().with_visuals(None)
    with pytest.raises(TypeError):
        snapshot().with_visuals("not a library")
    with pytest.raises(TypeError):
        wire_vehicle().with_game_labels(translations(), None)


@pytest.mark.parametrize("style,wanted", [
    ("SHORT", "A"), ("MEDIUM", "Car A"), ("LONG", "Maker Model A"),
    (CarNameStyle.LONG, "Maker Model A"), ("long", "Maker Model A"),
])
def test_vehicle_prefers_selected_car_name_style(style, wanted):
    bound = wire_vehicle().with_translations(translations(), style=style)
    assert bound.name == wanted
    assert bound.name.short == "A"
    assert bound.name.medium == "Car A"
    assert bound.name.long == "Maker Model A"
    assert bound.names == ["A", "Car A", "Maker Model A"]
    assert bound.preferred_name_style == CarNameStyle.coerce(style)
    assert wire_vehicle().with_translations(translations()).name == "Car A"


def test_missing_selected_style_never_falls_back():
    car = CrewMemberVehicle.from_wire({"current_car": "Car_B"})
    medium = car.with_translations(translations())
    assert medium.name == ""
    assert medium.name.medium is None
    assert medium.names == ["B", None, "Maker Model B"]
    long_name = car.with_translations(translations(), style="LONG")
    assert long_name.name == "Maker Model B"


def test_bad_style_is_rejected_before_modifying_source():
    source = wire_vehicle()
    with pytest.raises(ValueError):
        source.with_translations(translations(), style="CUSTOM")
    assert source.name is None
    assert source.visuals is None


def test_combined_binding_is_immutable_and_exposes_both_namespaces():
    before = snapshot()
    after = before.with_game_labels(translations(), visuals(), style="LONG")
    a = after.members[0].vehicle
    assert before.members[0].vehicle.name is None
    assert before.members[0].vehicle.visuals is None
    assert a.name == "Maker Model A"
    assert a.name.medium == "Car A"
    assert a.visuals.paint.name == "PRIVATE_PEARL"
    assert a.visuals.wheel.name == "PRIVATE_SPOKE"
    assert after.members[1].vehicle.name == "Maker Model B"
    assert after.members[1].vehicle.visuals.paint.name == "B PAINT"
    assert a.appearance.paint_id == 0
    assert len(after.members) == len(before.members)


def test_two_independent_snapshot_binding_paths_are_equivalent():
    one = snapshot().with_translations(translations(), style="SHORT").with_visuals(visuals())
    two = snapshot().with_game_labels(translations(), visuals(), style="SHORT")
    assert one.members[0].vehicle.name == two.members[0].vehicle.name == "A"
    assert one.members[0].vehicle.visuals.paint.name == two.members[0].vehicle.visuals.paint.name


def test_rebinding_visuals_does_not_keep_stale_labels():
    bound = wire_vehicle().with_visuals(visuals())
    blank = bound.with_visuals(GameVisualLibrary())
    assert bound.visuals.paint.name == "PRIVATE_PEARL"
    assert blank.visuals.paint.name is None
    assert blank.visuals.paint.code == 0


def test_default_output_and_repr_remain_private():
    bound = snapshot().with_game_labels(translations(), visuals())
    serialized = json.dumps(optional_report(bound), ensure_ascii=False)
    assert 'PRIVATE_PERSON_ONE' not in serialized
    assert 'PRIVATE_PEARL' not in serialized
    assert 'PRIVATE_SPOKE' not in serialized
    assert 'PRIVATE_CREW' not in serialized
    assert 'Maker Model A' not in serialized
    assert 'translated_names' not in serialized
    assert 'visuals' not in serialized
    assert 'PRIVATE_PEARL' not in repr(bound)
    assert 'PRIVATE_PEARL' not in repr(bound.members[0].vehicle.visuals.paint)
    # Legacy opt-in diagnostics remain JSON-serializable and don't dump bindings.
    expanded = json.dumps(optional_report(bound, show_members=True), ensure_ascii=False)
    assert 'translated_names' not in expanded
    assert 'preferred_name_style' not in expanded
    assert 'PRIVATE_PEARL' not in expanded  # shown only in separate game_label_report


def test_game_label_coverage_respects_no_implicit_show_members():
    bound = snapshot().with_game_labels(translations(), visuals())
    hidden = game_label_report(bound, names=translations(), visuals=visuals())
    assert hidden['car_names_resolved'] == 1
    assert hidden['visual_codes_resolved']['paint'] == 2
    assert hidden['visual_codes_resolved']['wheel'] == 1
    assert 'PRIVATE_PEARL' not in json.dumps(hidden)
    shown = game_label_report(bound, names=translations(), visuals=visuals(), show_members=True)
    assert shown['member_labels'][0]['visual_names']['paint']['name'] == 'PRIVATE_PEARL'
    assert shown['member_labels'][0]['visual_names']['wheel']['name'] == 'PRIVATE_SPOKE'


def test_wrong_name_source_type_is_rejected_on_combined_bind():
    with pytest.raises(TypeError):
        snapshot().with_game_labels({}, visuals())


def test_bound_visuals_are_visible_to_game_label_report_without_resupplying_catalog():
    bound = snapshot().with_visuals(visuals())
    result = game_label_report(bound)
    assert result['visual_library_records'] == 0  # no local catalog passed again
    assert result['visual_label_bindings_present'] == 2
    assert result['visual_codes_resolved']['paint'] == 2
    assert result['visual_codes_resolved']['wheel'] == 1
    assert 'member_labels' not in result
    shown = game_label_report(bound, show_members=True)
    assert shown['member_labels'][0]['visual_names']['paint']['name'] == 'PRIVATE_PEARL'


def test_bound_visual_codes_do_not_resolve_after_raw_appearance_changes():
    from dataclasses import replace
    bound = wire_vehicle().with_visuals(visuals())
    modified = replace(bound, appearance=replace(bound.appearance, paint_id=112))
    snap = CrewOptionalSnapshot('CREW', members=(
        __import__('csr2cdn').crew_optional_data.CrewMemberOptional(vehicle=modified),))
    outcome = game_label_report(snap)
    assert outcome['visual_codes_present']['paint'] == 1
    assert outcome['visual_codes_resolved']['paint'] == 0
