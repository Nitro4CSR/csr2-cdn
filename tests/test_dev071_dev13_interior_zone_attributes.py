"""Offline, privacy-safe compatibility checks for native interior zone attributes."""
import json
from dataclasses import replace

import pytest

from csr2cdn import (CrewMemberVehicle, InteriorDisplayName,
                     GameVisualLibrary, VisualCodeName)
from csr2cdn.visual_library_bundle import decode_visual_unityfs


def _vehicle(names=('Fabric', 'Leather')):
    record = VisualCodeName('*', 'interior', 123, names[0],
                            'CarInteriorLibrary', names=names)
    library = GameVisualLibrary((record,))
    vehicle = CrewMemberVehicle.from_wire({'current_car':'SomeModel', 'car_interior_id':123})
    return vehicle.with_visuals(library)


def test_interior_attribute_chain_and_backward_compatibility():
    car = _vehicle()
    name = car.visuals.interior.name
    assert isinstance(name, InteriorDisplayName)
    assert isinstance(name, str)
    assert name == 'Fabric' and f'{name}' == 'Fabric'
    assert str(name) == name.zone1 == 'Fabric'
    assert name.zone2 == 'Leather'
    assert car.visuals.interior.names == ('Fabric', 'Leather')
    assert json.dumps({'interior': name}) == '{"interior": "Fabric"}'
    assert car.visuals.interior.resolved


def test_single_name_source_does_not_invent_second_zone():
    car = _vehicle(('Fabric',))
    assert car.visuals.interior.name.zone1 == 'Fabric'
    assert car.visuals.interior.name.zone2 is None
    assert car.visuals.interior.names == ('Fabric',)


def test_manual_normalized_source_with_no_names_still_has_zone1():
    record = VisualCodeName('*', 'interior', 123, 'Fabric', 'manual')
    car = CrewMemberVehicle.from_wire({'car_interior_id':123}).with_visuals(GameVisualLibrary((record,)))
    assert car.visuals.interior.name.zone1 == 'Fabric'
    assert car.visuals.interior.name.zone2 is None
    assert car.visuals.interior.names == ()


def test_unknown_interior_id_stays_unresolved():
    record = VisualCodeName('*', 'interior', 1, 'Fabric', 'sample', names=('Fabric','Leather'))
    car = CrewMemberVehicle.from_wire({'car_interior_id':123}).with_visuals(GameVisualLibrary((record,)))
    assert car.visuals.interior.name is None
    assert car.visuals.interior.code == 123
    assert not car.visuals.interior.resolved


def test_other_visual_slots_keep_plain_strings():
    library = GameVisualLibrary((VisualCodeName('*','paint',123,'Glossy','CarPaintLibrary'),
                                 VisualCodeName('*','interior',123,'Fabric','CarInteriorLibrary',names=('Fabric','Leather'))))
    car = CrewMemberVehicle.from_wire({'car_paint_id':123,'car_interior_id':123}).with_visuals(library)
    assert type(car.visuals.paint.name) is str
    assert car.visuals.paint.name == 'Glossy'
    assert car.visuals.interior.name.zone2 == 'Leather'


def test_provenance_and_repr_privacy_preserved():
    vehicle = _vehicle()
    assert vehicle.visuals.interior.source_library == 'CarInteriorLibrary'
    assert 'Fabric' not in repr(vehicle.visuals.interior)
    assert 'Leather' not in repr(vehicle.visuals.interior)
    assert 'Fabric' not in repr(vehicle)


def test_zone_name_is_string_compatible_when_nested():
    name = InteriorDisplayName('Front', 'Rear')
    assert [name, 'Rear'] == ['Front','Rear']
    assert name.upper() == 'FRONT'
    assert name.zone1 == 'Front' and name.zone2 == 'Rear'


def test_interior_name_requires_nonempty_zone_one():
    with pytest.raises(ValueError): InteriorDisplayName('')
    with pytest.raises(ValueError): InteriorDisplayName('Front', 123)
