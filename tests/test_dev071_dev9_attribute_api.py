"""Dev9 attribute-first API; synthetic fixtures, no network or private data."""
from dataclasses import FrozenInstanceError
import json
import pytest

from csr2cdn import (CarDisplayName, CarNameStyle, GameCarName, GameCarTranslations,
                     CrewMemberVehicle, CrewOptionalSnapshot, load_localisation_unityfs)
from csr2cdn.game_labels import game_label_report, GameVisualLibrary
from csr2cdn.crew_optional_data import optional_report
from csr2cdn.service_models import OwnCrew, CrewMembers


def translations():
    return GameCarTranslations.from_manifest({
        'format': 'csr2cdn.car-translations.v1',
        'records': [
            {'model_key': 'Car_A', 'SHORT': 'A', 'MEDIUM': 'Car A', 'LONG': 'Manufacturer A'},
            {'model_key': 'Car_B', 'SHORT': 'B', 'LONG': 'Manufacturer B'},
        ],
    })


def optional_snapshot():
    own = OwnCrew.from_response({'crew_uid':'PRIVATE_CREW', 'members': 2})
    roster = CrewMembers.from_response('PRIVATE_CREW', {'crew_uid':'PRIVATE_CREW','scores':[
        {'player_uid':'PRIVATE_A','name':'PRIVATE_USER_ALPHA', 'current_car':'Car_A', 'cc_contrib':25},
        {'player_uid':'PRIVATE_B','name':'PRIVATE_USER_BETA', 'current_car':'Car_B', 'cc_contrib':32},
    ]})
    return CrewOptionalSnapshot.from_reads(own, roster)


def test_name_is_str_compatible_medium_by_default():
    car = translations().match('Car_A')
    assert car.name == 'Car A'
    assert str(car.name) == 'Car A'
    assert isinstance(car.name, str)
    assert isinstance(car.name, CarDisplayName)
    assert car.name.short == 'A'
    assert car.name.medium == 'Car A'
    assert car.name.long == 'Manufacturer A'
    assert car.name.style == CarNameStyle.MEDIUM
    assert f'{car.name}' == 'Car A'


def test_names_are_list_and_copy_in_documented_order():
    car = translations().match('Car_A')
    assert car.names == ['A', 'Car A', 'Manufacturer A']
    assert car.name.names == ['A', 'Car A', 'Manufacturer A']
    a = car.names
    a[0] = 'Changed locally'
    assert car.names == ['A', 'Car A', 'Manufacturer A']
    assert car.name.short == 'A'


def test_missing_medium_is_not_silently_replaced():
    car = translations().match('Car_B')
    assert car.choose() is None
    assert car.name == ''
    assert not car.name
    assert car.name.medium is None
    assert car.name.short == 'B'
    assert car.name.long == 'Manufacturer B'
    assert car.names == ['B', None, 'Manufacturer B']
    assert car.name.for_style('LONG') == 'Manufacturer B'


@pytest.mark.parametrize('style,value',[('SHORT','A'),('medium','Car A'),('LONG','Manufacturer A')])
def test_explicit_style_keeps_access_to_all_names(style,value):
    car = translations().match('Car_A')
    preferred = car.name.for_style(style)
    assert preferred == value
    assert preferred.long == 'Manufacturer A'
    assert preferred.names == car.names
    assert car.name == 'Car A'  # no mutation
    assert car.choose(style) == value  # legacy still works


def test_invalid_style_still_fails_closed():
    with pytest.raises(ValueError):
        translations().match('Car_A').name.for_style('UNKNOWN')


def test_vehicle_binding_is_immutable_and_attribute_first():
    source = CrewMemberVehicle.from_wire({'current_car':'Car_A','car_pp':550})
    assert source.name is None
    assert source.names == []
    bound = source.with_translations(translations())
    assert bound is not source
    assert source.name is None
    assert bound.model_key == 'Car_A'
    assert bound.pp == 550
    assert bound.name == 'Car A'
    assert bound.name.long == 'Manufacturer A'
    assert bound.names == ['A','Car A','Manufacturer A']
    with pytest.raises(FrozenInstanceError):
        bound.model_key = 'Changed'


def test_unmatched_vehicle_does_not_make_up_name():
    source = CrewMemberVehicle.from_wire({'current_car':'Not_In_Translations'})
    bound = source.with_translations(translations())
    assert bound.name is None
    assert bound.names == []


def test_snapshot_offline_binding_applies_to_existing_vehicle_projection():
    snap = optional_snapshot()
    bound = snap.with_translations(translations())
    assert snap.members[0].vehicle.name is None
    assert bound.members[0].vehicle.name.long == 'Manufacturer A'
    assert bound.members[1].vehicle.name.long == 'Manufacturer B'
    assert bound.members[1].vehicle.name.medium is None
    assert bound.members[1].vehicle.names == ['B', None, 'Manufacturer B']
    assert bound.crew_id == snap.crew_id
    assert bound.members[0].player_uid == snap.members[0].player_uid
    assert bound is not snap


def test_rebinding_replaces_old_name_without_stale_fallback():
    snap = optional_snapshot().with_translations(translations())
    empty = GameCarTranslations()
    again = snap.with_translations(empty)
    assert again.members[0].vehicle.name is None
    assert again.members[1].vehicle.names == []


def test_wrong_binders_are_rejected():
    with pytest.raises(TypeError):
        CrewMemberVehicle.from_wire({}).with_translations(None)
    with pytest.raises(TypeError):
        optional_snapshot().with_translations({})


def test_existing_diagnostics_do_not_serialize_bound_translation_values():
    bound = optional_snapshot().with_translations(translations())
    output = optional_report(bound)
    text = json.dumps(output)
    assert 'PRIVATE_USER_ALPHA' not in text
    assert 'Manufacturer A' not in text
    assert 'Car A' not in text
    assert 'translated_names' not in text
    out = optional_report(bound, show_members=True)
    assert 'translated_names' not in json.dumps(out)
    assert out['member_candidates'][0]['vehicle']['model_key'] == 'Car_A'


def test_game_label_report_keeps_default_private_and_opt_in_adds_all_three():
    bound = optional_snapshot().with_translations(translations())
    hidden = game_label_report(bound)
    assert hidden['car_names_resolved'] == 1
    assert 'member_labels' not in hidden
    assert 'Manufacturer A' not in json.dumps(hidden)
    shown = game_label_report(bound,show_members=True)
    assert shown['member_labels'][0]['car_name'] == 'Car A'
    assert shown['member_labels'][0]['car_names'] == ['A','Car A','Manufacturer A']
    assert shown['member_labels'][1]['car_name'] is None
    assert shown['member_labels'][1]['car_names'] == ['B',None,'Manufacturer B']
    assert game_label_report(bound,style='LONG')['car_names_resolved'] == 2


def test_old_car_and_visual_fields_still_work():
    car = translations().match('Car_A')
    assert (car.short,car.medium,car.long) == ('A','Car A','Manufacturer A')
    assert car.choose('LONG') == 'Manufacturer A'
    visuals = GameVisualLibrary.from_manifest({'format':'csr2cdn.visual-code-library.v1',
        'records':[{'model_key':'Car_A','slot':'paint','code':1,
                    'name':'Pearl', 'source_library':'CarPaintLibrary'}]})
    assert visuals.match('Car_A','paint',1).name == 'Pearl'


def test_public_unityfs_loader_export_is_present():
    assert callable(load_localisation_unityfs)
