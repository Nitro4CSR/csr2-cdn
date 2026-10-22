"""Offline tests for per-car cosmetic index spaces (Dev82).

Synthetic trees only: no network, no APK, no bundle fixtures. The anchor values
mirror Ford_Mustang302_1970 as published in asset database 34049.
"""
import pytest

from csr2cdn.car_visuals_data import (CAR_LIST_SLOTS, ELIGIBILITY_SLOTS, GACHA_SLOT_KEYS,
                                      INDEX_SLOTS, INT32_MAX, INT32_MIN,
                                      NUMBER_ZONE_ANCHOR, PLACEMENT_SLOTS, gacha_values,
                                      LIBRARY_SLOT_ALIASES, NAME_SLOTS, SENTINEL,
                                      TNR_ID_FLOOR, WHEEL_SENTINEL, ZERO_MEANS_NONE,
                                      CarVisualsError, common_asset_candidates,
                                      common_asset_code, compose_index_space,
                                      compose_valid_ids, library_slots, match_library,
                                      resolve_appearance, split_groups,
                                      strip_wheel_prefix)
from csr2cdn.game_labels import GameVisualLibrary
from csr2cdn.service_models import OwnCrew
from csr2cdn.errors import Csr2CdnError

# Ford_Mustang302_1970, database 34049.
ANCHOR_DEFAULT_PAINTS = [1156, 451, 1159, 1160]
ANCHOR_UNLOCK_PAINTS = [
    1160, 451, 1156, -1, 1164, 1163, 1162, -1, 1157, 1158, 1161, -1,
    1138, 1251, 1247, -1, 1248, 129, 1323, -1, 1246, 518, 131, -1,
    121, 125, 119, -1, 127, 126, 133, -1, 132, 1321, 1322, -1, 1297, 510, 1159,
]


def anchor_space():
    visuals = {
        "CarPaintIDs": list(ANCHOR_DEFAULT_PAINTS),
        "CarInteriorIDs": [66],
        "CarCalliperIDs": [4],
        "CarLiveryZonesSetIDs": [0],
        "CarLiveryIDs": [422],
        "WheelBundleNames": ["Wheel1A_3D"],
        "lockPaintsToIndex": 0,
        "HasOwnLivery": 0,
        "GachaConfigs": [{}] * 11,
    }
    unlockables = {"AllUnlockables": {
        "type": 0,
        "carPaintIDs": list(ANCHOR_UNLOCK_PAINTS),
        "carInteriorIDs": [66, 888, 887, 886, 885, 884],
        "carCalliperIDs": [9, 1, 6, 3, 2, 7],
        "carLiverySetIDs": [17, 23, 21, 19, 15],
        "wheelBundleNames": ["Wheel1A_3D", "Wheel3A_3D", "Wheel2A_3D"],
        "licensePlateCategories": ["Retro"],
        "carKits": [],
    }}
    return compose_index_space("Ford_Mustang302_1970", visuals, unlockables,
                               database_version="34049", asset_version="14")


def library():
    rows = [
        {"model_key": "*", "slot": "paint", "code": 1156, "name": "Ford Calypso Coral",
         "source_library": "CarPaintLibrary"},
        {"model_key": "*", "slot": "paint", "code": 1323, "name": "Ford Dark Highland Green",
         "source_library": "CarPaintLibrary"},
        {"model_key": "*", "slot": "interior", "code": 887, "name": "Ford Ginger",
         "source_library": "CarInteriorLibrary"},
        {"model_key": "*", "slot": "calliper", "code": 9, "name": "Global Dark Grey",
         "source_library": "CarCalliperLibrary"},
        {"model_key": "*", "slot": "livery_set", "code": 21,
         "name": "Ford Mustang 302 Design 1 Red Hood", "source_library": "CarLiverySetLibrary"},
        {"model_key": "*", "slot": "livery", "code": 422, "name": "Ford Mustang Boss 302",
         "source_library": "CarLiveryLibrary"},
        {"model_key": "*", "slot": "color", "code": 4, "name": "Red",
         "source_library": "CarColorLibrary"},
    ]
    return GameVisualLibrary.from_manifest(
        {"format": "csr2cdn.visual-code-library.v1", "records": rows})


# -- ragged list handling -------------------------------------------------
@pytest.mark.parametrize("flat,expected", [
    ([1, 2, -1, 3, -1], ((1, 2), (3,))),
    ([1, -1, -1, 2], ((1,), (2,))),
    ([1, 2, 3], ((1, 2, 3),)),
    ([-1], ()),
    ([], ()),
    (None, ()),
])
def test_split_groups(flat, expected):
    assert split_groups(flat) == expected


def test_split_groups_wheel_sentinel_is_a_string():
    assert split_groups(["a", "-1", "b"], WHEEL_SENTINEL) == (("a",), ("b",))


def test_split_groups_rejects_absurd_length():
    with pytest.raises(CarVisualsError):
        split_groups([0] * 10000)


def test_compose_preserves_order_and_drops_repeats():
    assert compose_valid_ids([5, 5, 7], [7, 9, -1, 5, 11]) == (5, 7, 9, 11)


def test_compose_drops_sentinels_from_defaults_too():
    assert compose_valid_ids([1, -1, 2], None) == (1, 2)


def test_compose_without_unlockables_is_just_defaults():
    assert compose_valid_ids([3, 1, 2], None) == (3, 1, 2)


# -- the anchor -----------------------------------------------------------
def test_anchor_index_space_length():
    assert anchor_space().length("paint") == 30


@pytest.mark.parametrize("index,paint", [(0, 1156), (15, 1323), (29, 510)])
def test_anchor_indices(index, paint):
    assert anchor_space().resolve_index("paint", index) == paint


def test_anchor_round_trips():
    space = anchor_space()
    assert space.index_of("paint", 1323) == 15
    assert space.resolve_index("paint", space.index_of("paint", 1156)) == 1156


def test_out_of_range_and_bad_index_give_none():
    space = anchor_space()
    for bad in (30, 999, -1, None, "15", True, 1.0):
        assert space.resolve_index("paint", bad) is None


def test_unindexed_slot_resolves_to_none():
    assert anchor_space().resolve_index("livery", 0) is None


def test_every_car_list_slot_is_populated():
    space = anchor_space()
    for slot in CAR_LIST_SLOTS:
        assert space.length(slot) > 0, slot


def test_sentinels_never_enter_the_space():
    space = anchor_space()
    for slot in CAR_LIST_SLOTS:
        entries = space.valid[slot]
        assert SENTINEL not in entries and WHEEL_SENTINEL not in entries
        assert len(entries) == len(set(entries))


def test_lock_flag_shape():
    space = anchor_space()
    assert space.lock_paints_to_index == 0
    assert space.paints_locked is False


def test_locked_car_reports_locked():
    visuals = {"CarPaintIDs": [1, 2], "CarInteriorIDs": [], "CarCalliperIDs": [],
               "CarLiveryZonesSetIDs": [], "WheelBundleNames": [], "lockPaintsToIndex": 2}
    assert compose_index_space("X", visuals).paints_locked is True


# -- slot model ----------------------------------------------------------
def test_only_paint_is_indexed():
    """Live roster evidence: paint is a position, the rest are IDs."""
    assert INDEX_SLOTS == frozenset({"paint"})
    for slot in ("interior", "calliper", "livery_zones_set"):
        assert slot in ELIGIBILITY_SLOTS and slot not in INDEX_SLOTS
    # Every one of those still has a per-car list; that is what misled us.
    assert set(INDEX_SLOTS) | set(ELIGIBILITY_SLOTS) | set(NAME_SLOTS) == set(CAR_LIST_SLOTS)


def test_indexed_slots_alias_is_the_car_list_table():
    from csr2cdn.car_visuals_data import INDEXED_SLOTS
    assert INDEXED_SLOTS is CAR_LIST_SLOTS


# -- library vocabulary ---------------------------------------------------
def test_alias_table_covers_the_previously_unverified_joins():
    for slot in ("livery_zones_set", "decal_number_color", "decal_number_shape_color", "wheel"):
        assert slot in LIBRARY_SLOT_ALIASES


def test_library_slots_defaults_to_the_slot_itself():
    assert library_slots("paint") == ("paint",)
    assert "livery_zone_mask" in library_slots("livery_zones_set")
    assert library_slots("livery_set") == ("livery_set",)
    assert "color" in library_slots("decal_number_color")


def test_match_library_follows_the_alias():
    lib = GameVisualLibrary.from_manifest({
        "format": "csr2cdn.visual-code-library.v1",
        "records": [
            {"model_key": "*", "slot": "livery_zone_mask", "code": 9, "name": "CONTRAST",
             "source_library": "LiveryZonesSetLibrary"},
            {"model_key": "*", "slot": "livery_set", "code": 21,
             "name": "Ford Mustang 302 Design 1 Red Hood",
             "source_library": "LiverySetLibrary"},
        ]})
    # The wire slot is livery_zones_set; the library labels it livery_zone_mask.
    assert lib.match(None, "livery_zones_set", 9) is None
    assert match_library(lib, None, "livery_zones_set", 9).name == "CONTRAST"
    # A livery set is a different slot and must not be reachable through it.
    assert match_library(lib, None, "livery_zones_set", 21) is None
    assert match_library(lib, None, "livery_set", 21).name == \
        "Ford Mustang 302 Design 1 Red Hood"
    assert match_library(None, None, "paint", 1156) is None


# -- wheel names ----------------------------------------------------------
@pytest.mark.parametrize("wire,model,expected", [
    ("Ford_Mustang302_1970_Wheel1A_3D", "Ford_Mustang302_1970", "Wheel1A_3D"),
    ("Wheel1A_3D", "Ford_Mustang302_1970", "Wheel1A_3D"),
    ("Other_Car_Wheel1A_3D", "Ford_Mustang302_1970", "Other_Car_Wheel1A_3D"),
    (None, "Ford_Mustang302_1970", None),
    ("Wheel1A_3D", None, "Wheel1A_3D"),
])
def test_strip_wheel_prefix(wire, model, expected):
    assert strip_wheel_prefix(wire, model) == expected


# -- appearance resolution ------------------------------------------------
class Appearance:
    """Values as the live roster sends them."""
    paint_id = 15
    interior_id = 887
    calliper_id = 9
    livery_zones_set_id = 21
    wheel_name = "Ford_Mustang302_1970_Wheel1A_3D"
    livery_id = 422
    decal_number_color_id = 4


def resolved():
    return resolve_appearance(Appearance(), anchor_space(), library(),
                              model_key="Ford_Mustang302_1970")


def test_paint_resolves_through_the_index():
    paint = resolved()["paint"]
    assert paint["global_id"] == 1323
    assert paint["name"] == "Ford Dark Highland Green"
    assert paint["status"] == "resolved_via_index"
    assert paint["indexed"] is True
    assert paint["eligible"] is True


def test_other_slots_are_global_ids_not_positions():
    out = resolved()
    assert out["interior"]["global_id"] == 887
    assert out["interior"]["name"] == "Ford Ginger"
    assert out["interior"]["status"] == "resolved_global_id"
    assert out["interior"]["indexed"] is False
    assert out["calliper"]["global_id"] == 9
    assert out["calliper"]["name"] == "Global Dark Grey"
    assert out["livery"]["status"] == "resolved_global_id"
    assert out["decal_number_color"]["name"] == "Red"


def test_car_list_validates_eligibility_for_global_slots():
    out = resolved()
    assert out["interior"]["eligible"] is True
    assert out["calliper"]["eligible"] is True

    class Foreign(Appearance):
        interior_id = 2199  # a real library ID this car may not wear
    out = resolve_appearance(Foreign(), anchor_space(), library(),
                             model_key="Ford_Mustang302_1970")
    assert out["interior"]["eligible"] is False
    # Ineligible is not unresolved: the label is still correct.
    assert out["interior"]["global_id"] == 2199


def test_eligibility_is_unknown_without_a_bundle():
    out = resolve_appearance(Appearance(), None, library(), model_key="X")
    assert out["interior"]["eligible"] is None
    assert out["interior"]["status"] == "resolved_global_id"


def test_wheel_strips_the_model_prefix_and_checks_the_list():
    wheel = resolved()["wheel"]
    assert wheel["global_id"] == "Wheel1A_3D"
    assert wheel["status"] == "resolved_name"
    assert wheel["eligible"] is True


def test_wheel_absent_from_the_bundle_list_is_not_called_invalid():
    """Classic models list only some of their rims, yet the assets exist."""
    class Odd(Appearance):
        wheel_name = "Ford_Mustang302_1970_Wheel99Z_3D"
    out = resolve_appearance(Odd(), anchor_space(), library(), model_key="Ford_Mustang302_1970")
    assert out["wheel"]["status"] == "name_not_in_bundle_list"
    assert out["wheel"]["global_id"] == "Wheel99Z_3D"
    assert out["wheel"]["eligible"] is None


def test_wheel_wire_value_is_the_asset_code():
    wheel = resolved()["wheel"]
    assert wheel["asset_code"] == "Ford_Mustang302_1970_Wheel1A_3D"
    assert wheel["global_id"] == "Wheel1A_3D"


def test_wheel_without_a_bundle_still_yields_the_name():
    out = resolve_appearance(Appearance(), None, library(), model_key="Ford_Mustang302_1970")
    assert out["wheel"]["status"] == "resolved_name_car_unknown"
    assert out["wheel"]["global_id"] == "Wheel1A_3D"


def test_no_slot_treats_zero_as_an_absence():
    """Dropped: zone mask 0 is FULL BODY, a real record. See the zone test below."""
    assert ZERO_MEANS_NONE == frozenset()


def test_tuner_stars_paint_is_a_global_id_not_an_index():
    class Tnr(Appearance):
        paint_id = TNR_ID_FLOOR + 115
    out = resolve_appearance(Tnr(), anchor_space(), library(), model_key="X")
    assert out["paint"]["global_id"] == TNR_ID_FLOOR + 115
    assert out["paint"]["tuner_stars"] is True
    assert out["paint"]["status"] == "global_id_not_in_library"


def test_paint_without_a_bundle_is_reported_not_guessed():
    out = resolve_appearance(Appearance(), None, library(), model_key="X")
    assert out["paint"]["status"] == "no_index_space"
    assert out["paint"]["global_id"] is None


def test_paint_index_past_the_public_list_is_flagged():
    """A player's gacha or aftermarket paints can extend the shipped list."""
    class Far(Appearance):
        paint_id = 30
    out = resolve_appearance(Far(), anchor_space(), library(), model_key="X")
    assert out["paint"]["status"] == "index_out_of_range"
    assert out["paint"]["list_length"] == 30


def test_absent_fields_are_omitted():
    class Sparse:
        paint_id = None
        interior_id = 887
    out = resolve_appearance(Sparse(), anchor_space(), library(), model_key="X")
    assert "paint" not in out and "interior" in out


# -- input validation -----------------------------------------------------
def test_compose_requires_a_model_key_and_the_marker():
    with pytest.raises(CarVisualsError):
        compose_index_space("", {"CarPaintIDs": []})
    with pytest.raises(CarVisualsError):
        compose_index_space("X", {"nope": 1})
    with pytest.raises(CarVisualsError):
        compose_index_space("X", {"CarPaintIDs": []}, {"AllUnlockables": 5})


def test_non_list_default_is_rejected():
    with pytest.raises(CarVisualsError):
        compose_index_space("X", {"CarPaintIDs": "nope"})


def test_errors_are_package_errors():
    assert issubclass(CarVisualsError, Csr2CdnError)


@pytest.mark.parametrize("model,expected", [
    ("Ford_Mustang302_1970", "Ford_Mustang302_1970_common"),
    ("Ford_Mustang302_1970_common", "Ford_Mustang302_1970_common"),
])
def test_common_asset_code(model, expected):
    assert common_asset_code(model) == expected


def test_candidates_fall_back_to_the_bare_model_key():
    """Classic restoration models ship cosmetics under the model name alone."""
    assert common_asset_candidates("Ferrari_250GTOClassic_1962") == (
        "Ferrari_250GTOClassic_1962_common", "Ferrari_250GTOClassic_1962")
    assert common_asset_candidates("X_common") == ("X_common", "X")


def test_as_dict_is_serializable():
    data = anchor_space().as_dict()
    assert data["lengths"]["paint"] == 30
    assert data["database_version"] == "34049"
    assert data["valid"]["paint"][15] == 1323


# -- the crewless envelope ------------------------------------------------
def test_crewless_envelope_decodes():
    record = OwnCrew.from_response({"Error": "Player not in crew", "error_code": 306,
                                    "player_uid": "x", "total_invites": 0})
    assert record.in_crew is False and record.crew_uid is None


@pytest.mark.parametrize("payload", [
    {"Error": "Player not in crew", "error_code": 99},
    {"Error": "Some other failure", "error_code": 306},
    {"error_code": 306},
    {"unrelated": 1},
    {},
])
def test_other_envelopes_still_raise(payload):
    from csr2cdn.service_models import ServiceResponseError
    with pytest.raises(ServiceResponseError):
        OwnCrew.from_response(payload)


def test_real_membership_is_unaffected():
    record = OwnCrew.from_response({"crewUID": "abc123", "crewName": "n", "memberCount": 5})
    assert record.in_crew is True and record.crew_uid == "abc123"


# -- gacha cosmetics ------------------------------------------------------
def test_gacha_values_skips_sentinels_and_repeats():
    configs = [
        {"PaintID": 10, "WrapPaintID": INT32_MAX, "WheelBundleName": "Wheel1A_3D"},
        {"PaintID": 10, "WrapPaintID": INT32_MIN, "WheelBundleName": "-1"},
        {"PaintID": 11, "WheelBundleName": ""},
    ]
    assert gacha_values(configs, "PaintID") == (10, 11)
    assert gacha_values(configs, "WrapPaintID") == ()
    assert gacha_values(configs, "WheelBundleName") == ("Wheel1A_3D",)
    assert gacha_values(None, "PaintID") == ()
    assert gacha_values("nope", "PaintID") == ()


def test_gacha_paints_extend_the_index_space_at_the_end():
    """A roster index past the shipped list is filled by the car's gacha paints."""
    visuals = {
        "CarPaintIDs": [1, 2], "CarInteriorIDs": [], "CarCalliperIDs": [],
        "CarLiveryZonesSetIDs": [], "WheelBundleNames": [],
        "GachaConfigs": [{"PaintID": 2}, {"PaintID": 99}, {"PaintID": INT32_MAX}],
    }
    space = compose_index_space("X", visuals)
    assert space.valid["paint"] == (1, 2, 99)
    assert space.gacha["paint"] == (2, 99)
    assert space.resolve_index("paint", 2) == 99
    assert space.gacha_config_count == 3
    # Existing indices keep their meaning.
    assert space.resolve_index("paint", 0) == 1


def test_gacha_keys_cover_every_car_list_slot_that_has_one():
    for slot in GACHA_SLOT_KEYS:
        assert slot in CAR_LIST_SLOTS


# -- number zones ---------------------------------------------------------
def test_number_zone_is_a_placement_not_a_library_record():
    assert PLACEMENT_SLOTS == frozenset({"decal_number_zone"})

    class WithZone(Appearance):
        decal_number_zone_id = 1
    space = anchor_space()
    out = resolve_appearance(WithZone(), space, library(), model_key="X")
    zone = out["decal_number_zone"]
    assert zone["status"] == "resolved_placement"
    assert zone["anchor"] == NUMBER_ZONE_ANCHOR + "1"
    assert zone["name"] == "RacingNumber1"


def test_number_zone_bounds_apply_only_when_the_count_is_known():
    from dataclasses import replace

    class Far(Appearance):
        decal_number_zone_id = 9
    space = anchor_space()
    assert space.number_zone_count is None
    out = resolve_appearance(Far(), space, library(), model_key="X")
    assert out["decal_number_zone"]["status"] == "resolved_placement"

    bounded = replace(space, number_zone_count=3)
    out = resolve_appearance(Far(), bounded, library(), model_key="X")
    assert out["decal_number_zone"]["status"] == "placement_out_of_range"
    assert out["decal_number_zone"]["zone_count"] == 3


def test_negative_placement_is_invalid():
    class Bad(Appearance):
        decal_number_zone_id = -1
    out = resolve_appearance(Bad(), anchor_space(), library(), model_key="X")
    assert out["decal_number_zone"]["status"] == "invalid_placement"


# -- labels belong to the ID, not the car --------------------------------
def test_label_falls_back_across_model_keys():
    """Some records are bound to one model; the label is still correct."""
    lib = GameVisualLibrary.from_manifest({
        "format": "csr2cdn.visual-code-library.v1",
        "records": [{"model_key": "Toyota_GRSupraTNR_2020", "slot": "interior",
                     "code": 1000133, "name": "Toyota Black Leather",
                     "source_library": "CarTunerStarsInteriorLibrary"}]})
    assert lib.match("Toyota_SupraMK4TNR_1994", "interior", 1000133) is None
    found = match_library(lib, "Toyota_SupraMK4TNR_1994", "interior", 1000133)
    assert found is not None and found.name == "Toyota Black Leather"


def test_own_model_and_global_records_still_win_first():
    lib = GameVisualLibrary.from_manifest({
        "format": "csr2cdn.visual-code-library.v1",
        "records": [
            {"model_key": "OtherCar", "slot": "paint", "code": 7, "name": "wrong",
             "source_library": "CarPaintLibrary"},
            {"model_key": "*", "slot": "paint", "code": 7, "name": "global",
             "source_library": "CarPaintLibrary"},
            {"model_key": "MyCar", "slot": "paint", "code": 7, "name": "mine",
             "source_library": "CarPaintLibrary"},
        ]})
    assert match_library(lib, "MyCar", "paint", 7).name == "mine"
    assert match_library(lib, "Unknown", "paint", 7).name == "global"


def test_fallback_respects_the_slot():
    lib = GameVisualLibrary.from_manifest({
        "format": "csr2cdn.visual-code-library.v1",
        "records": [{"model_key": "SomeCar", "slot": "paint", "code": 1000133,
                     "name": "a paint", "source_library": "CarTunerStarsPaintLibrary"}]})
    assert match_library(lib, "Other", "interior", 1000133) is None
    assert match_library(lib, "Other", "paint", 1000133).name == "a paint"


# -- typetree library decoder --------------------------------------------
def test_typetree_decoder_knows_every_shipped_library():
    from csr2cdn.visual_library_typetree import LIBRARY_SLOTS
    for name in ("CarTunerStarsLiveryLibrary", "CarTunerStarsLiverySetLibrary",
                 "CarTunerStarsTireLibrary", "CarTunerStarsBoostColorLibrary"):
        assert name in LIBRARY_SLOTS, name
    assert LIBRARY_SLOTS["CarTunerStarsLiveryLibrary"] == "livery"


def test_typetree_record_list_picks_the_longest_id_bearing_list():
    from csr2cdn.visual_library_typetree import _entries
    tree = {"m_Name": "x", "ExclusionListPaintIDKey": [1, 2, 3],
            "CarTNRLiveries": [{"ID": 1, "NameID": "a"}, {"ID": 2, "NameID": "b"}]}
    assert len(_entries(tree)) == 2
    assert _entries({"m_Name": "x", "nothing": [1, 2]}) is None


def test_typetree_decoder_rejects_unknown_libraries():
    from csr2cdn.visual_library_typetree import VisualTypetreeError, decode_library_typetree
    with pytest.raises(VisualTypetreeError):
        decode_library_typetree(b"x", "NotALibrary")
    with pytest.raises(VisualTypetreeError):
        decode_library_typetree(b"", "CarPaintLibrary")


def test_merge_keeps_the_first_label_per_code():
    from csr2cdn.visual_library_typetree import merge
    a = GameVisualLibrary.from_manifest({
        "format": "csr2cdn.visual-code-library.v1",
        "records": [{"model_key": "*", "slot": "paint", "code": 1, "name": "first",
                     "source_library": "CarPaintLibrary"}]})
    b = GameVisualLibrary.from_manifest({
        "format": "csr2cdn.visual-code-library.v1",
        "records": [{"model_key": "*", "slot": "paint", "code": 1, "name": "second",
                     "source_library": "CarTunerStarsPaintLibrary"},
                    {"model_key": "*", "slot": "tire", "code": 5, "name": "a tire",
                     "source_library": "CarTunerStarsTireLibrary"}]})
    merged = merge([a, b])
    assert len(merged.records) == 2
    assert merged.match("*", "paint", 1).name == "first"
    assert merged.match("*", "tire", 5).name == "a tire"


# -- the corrected livery zone slot --------------------------------------
def test_livery_zone_slot_prefers_the_mask_library():
    from csr2cdn.car_visuals_data import LIBRARY_SLOT_ALIASES
    assert "livery_zone_mask" in LIBRARY_SLOT_ALIASES["livery_zones_set"]
    assert "livery_set" not in LIBRARY_SLOT_ALIASES["livery_zones_set"]


def test_zone_masks_and_livery_sets_are_separate_car_lists():
    """CarLiveryZonesSetIDs and carLiverySetIDs name different libraries."""
    from csr2cdn.car_visuals_data import CAR_LIST_SLOTS
    masks_default, masks_unlock, _ = CAR_LIST_SLOTS["livery_zones_set"]
    sets_default, sets_unlock, _ = CAR_LIST_SLOTS["livery_set"]
    assert masks_default == "CarLiveryZonesSetIDs" and masks_unlock is None
    assert sets_default is None and sets_unlock == "carLiverySetIDs"

    visuals = {"CarPaintIDs": [], "CarLiveryZonesSetIDs": [0, 9], "CarInteriorIDs": [],
               "CarCalliperIDs": [], "WheelBundleNames": []}
    unlock = {"AllUnlockables": {"carLiverySetIDs": [17, 21]}}
    space = compose_index_space("X", visuals, unlock)
    assert space.valid["livery_zones_set"] == (0, 9)
    assert space.valid["livery_set"] == (17, 21)


def test_zero_is_a_real_zone_mask_not_an_absence():
    from csr2cdn.car_visuals_data import ZERO_MEANS_NONE
    assert ZERO_MEANS_NONE == frozenset()

    lib = GameVisualLibrary.from_manifest({
        "format": "csr2cdn.visual-code-library.v1",
        "records": [{"model_key": "*", "slot": "livery_zone_mask", "code": 0,
                     "name": "FULL BODY", "source_library": "LiveryZonesSetLibrary"}]})

    class Full(Appearance):
        livery_zones_set_id = 0
    out = resolve_appearance(Full(), None, lib, model_key="X")
    assert out["livery_zones_set"]["name"] == "FULL BODY"
    assert out["livery_zones_set"]["status"] == "resolved_global_id"


def test_int32_min_is_the_unset_marker():
    class Unset(Appearance):
        livery_zones_set_id = INT32_MIN
        interior_id = INT32_MAX
    out = resolve_appearance(Unset(), anchor_space(), library(), model_key="X")
    assert out["livery_zones_set"]["status"] == "unset"
    assert out["interior"]["status"] == "unset"
    assert out["livery_zones_set"]["global_id"] is None


# -- number placement, not a boolean -------------------------------------
@pytest.mark.parametrize("value,visible,status", [
    (0, False, "resolved_placement"),
    (1, True, "resolved_placement"),
    (3, True, "resolved_placement"),
    (-2, None, "invalid_placement"),
])
def test_number_zone_is_a_placement_selector(value, visible, status):
    class Row(Appearance):
        decal_number_zone_id = value
    out = resolve_appearance(Row(), anchor_space(), library(), model_key="X")
    zone = out["decal_number_zone"]
    assert zone["status"] == status
    assert zone["visible"] is visible


def test_number_zone_3_rules_out_a_boolean():
    """A live roster row reports 3, which no 0/1 flag produces."""
    class Third(Appearance):
        decal_number_zone_id = 3
    out = resolve_appearance(Third(), anchor_space(), library(), model_key="X")
    assert out["decal_number_zone"]["anchor"] == "RacingNumber3"


def test_number_zone_bounded_when_the_anchor_count_is_known():
    from dataclasses import replace
    from csr2cdn.car_visuals_data import NUMBER_ZONE_ANCHORS_PER_CAR

    class Far(Appearance):
        decal_number_zone_id = 9
    bounded = replace(anchor_space(), number_zone_count=NUMBER_ZONE_ANCHORS_PER_CAR)
    out = resolve_appearance(Far(), bounded, library(), model_key="X")
    assert out["decal_number_zone"]["status"] == "placement_out_of_range"


# -- car_tnr_setup and car_gacha_config ----------------------------------
def tnr_library():
    return GameVisualLibrary.from_manifest({
        "format": "csr2cdn.visual-code-library.v1",
        "records": [
            {"model_key": "*", "slot": "tuner_rim", "code": 1000200, "name": "84A",
             "source_library": "CarTunerStarsRimLibrary"},
            {"model_key": "*", "slot": "boost_color", "code": 1000001, "name": "Standard",
             "source_library": "CarTunerStarsBoostColorLibrary"},
            {"model_key": "*", "slot": "tire", "code": 0, "name": "TOYO_ProxesR888_A",
             "source_library": "CarTunerStarsTireLibrary"},
            {"model_key": "*", "slot": "paint", "code": 2694,
             "name": "Porsche British Racing Green", "source_library": "CarPaintLibrary"},
            {"model_key": "*", "slot": "livery_zone_mask", "code": 9, "name": "CONTRAST",
             "source_library": "LiveryZonesSetLibrary"},
        ]})


def test_tnr_setup_resolves_the_wheel_name():
    from csr2cdn.crew_cosmetic_fields import TunerStarsSetup
    setup = TunerStarsSetup.from_wire(
        {"RIMS": 1000200, "BOOST_COLOR": 1000001, "TIRE": 0,
         "BODYKIT": 6, "HOOD": 0, "WING": 0, "WHEELS": 0}, tnr_library())
    assert setup.RIMS.name == "84A"
    assert setup.BOOST_COLOR.name == "Standard"
    assert setup.TIRE.name == "TOYO_ProxesR888_A"
    assert setup.BODYKIT.status == "no_library_known"
    assert set(setup.present) == {"RIMS", "BOOST_COLOR", "BODYKIT"}


def test_tnr_setup_zero_is_stock_not_a_failure():
    from csr2cdn.crew_cosmetic_fields import TunerStarsSetup
    setup = TunerStarsSetup.from_wire({"RIMS": 0, "BOOST_COLOR": 0}, tnr_library())
    assert setup.RIMS.status == "none_or_stock"
    assert setup.BOOST_COLOR.status == "none_or_stock"


def test_tnr_setup_rejects_junk():
    from csr2cdn.crew_cosmetic_fields import TunerStarsSetup
    assert TunerStarsSetup.from_wire(None) is None
    assert TunerStarsSetup.from_wire({}) is None
    assert TunerStarsSetup.from_wire("nope") is None


def test_gacha_config_resolves_a_full_cosmetic_set():
    from csr2cdn.crew_cosmetic_fields import GachaSelection
    gacha = GachaSelection.from_wire(
        {"paid": 2694, "inid": 1129, "caid": 5, "lzsid": 9,
         "livid": INT32_MIN, "whbn": "Wheel1A_3D"}, tnr_library())
    assert gacha.applied is True
    assert gacha.paint.name == "Porsche British Racing Green"
    assert gacha.livery_zones_set.name == "CONTRAST"
    assert gacha.livery.status == "unset"
    assert gacha.wheel.value == "Wheel1A_3D"


def test_gacha_config_empty_means_no_roll():
    from csr2cdn.crew_cosmetic_fields import GachaSelection
    assert GachaSelection.from_wire({}) is None
    nothing = GachaSelection.from_wire({"paid": INT32_MIN, "whbn": "-1"})
    assert nothing is not None and nothing.applied is False


def test_resolve_extra_cosmetics_reads_both_blocks():
    from csr2cdn.crew_cosmetic_fields import resolve_extra_cosmetics
    out = resolve_extra_cosmetics(
        {"car_tnr_setup": {"RIMS": 1000200}, "car_gacha_config": {"paid": 2694}},
        tnr_library())
    assert out["tuner_stars"].RIMS.name == "84A"
    assert out["gacha"].paint.name == "Porsche British Racing Green"
    assert resolve_extra_cosmetics(None) == {"tuner_stars": None, "gacha": None}
