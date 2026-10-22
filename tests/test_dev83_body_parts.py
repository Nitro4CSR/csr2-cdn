"""0.7.1.dev83 — the four upper-case car_tnr_setup body-part slots.

Asset shapes are taken from the live asset list: kit levels 0..K with K of 3
or 6, and 1 + 2K hood/wing options (0a, then Na and Nb per level above).
All 25 cars shipping the full triple are TNR models.

HOOD and WING are a variant selector over the fitted kit, bounded to {0, 1}
and forced to 0 while BODYKIT is 0 -- a game constraint the maintainer
confirmed, and one no car's asset set contradicts, since no car ships a `0b`.
"""
import pytest

from csr2cdn.car_body_parts import (
    BODY_PART_SLOTS, RETIRED_SLOTS, VARIANT_SLOTS, BodyPartSelection,
    CarBodyPartInventory, bodykit_asset_code, part_asset_code,
    resolve_body_parts, split_model_key)

CAR = "Honda_CivicEGTNR_1995"
BIG = "Honda_S2000TNR_2001"


def codes(stem, year, top):
    """The asset series a kit car ships, lower-cased as the CDN publishes it."""
    out = ["%s%d_%s_loda" % (stem, n, year) for n in range(top + 1)]
    for token in ("hood", "wing"):
        out.append("%s_%s_%s0a_loda" % (stem, year, token))
        for n in range(1, top + 1):
            out += ["%s_%s_%s%d%s_loda" % (stem, year, token, n, v) for v in "ab"]
    return [c.lower() for c in out]


CIVIC = codes("Honda_CivicEGTNR", "1995", 3)
S2000 = codes("Honda_S2000TNR", "2001", 6)


def inv(car=CAR, pool=None):
    return CarBodyPartInventory.from_asset_codes(pool or CIVIC, car)


# -- model key splitting -------------------------------------------------
def test_split_model_key():
    assert split_model_key(CAR) == ("Honda_CivicEGTNR", "1995")
    assert split_model_key("Pininfarina_B95_2025") == ("Pininfarina_B95", "2025")


@pytest.mark.parametrize("bad", [None, "", "NoYear", "Honda_Civic_95", 7])
def test_split_model_key_rejects_junk(bad):
    assert split_model_key(bad) == (None, None)


# -- asset code construction --------------------------------------------
def test_bodykit_level_is_spliced_into_the_stem():
    assert bodykit_asset_code(CAR, 1) == "Honda_CivicEGTNR1_1995_loda"
    assert bodykit_asset_code(CAR, 0) == "Honda_CivicEGTNR0_1995_loda"


def test_hood_and_wing_are_suffixed_not_spliced():
    assert part_asset_code(CAR, "HOOD", 2, "b") == "Honda_CivicEGTNR_1995_Hood2b_loda"
    assert part_asset_code(CAR, "WING", 0, "a") == "Honda_CivicEGTNR_1995_Wing0a_loda"


@pytest.mark.parametrize("args", [
    (CAR, "HOOD", 1, "c"), (CAR, "WHEELS", 1, "a"), (CAR, "BODYKIT", 1, "a"),
    (None, "HOOD", 1, "a"), (CAR, "HOOD", -1, "a"), (CAR, "HOOD", True, "a"),
])
def test_part_asset_code_refuses_nonsense(args):
    assert part_asset_code(*args) is None


@pytest.mark.parametrize("level", [-1, True, None, "1", 1.0])
def test_bodykit_code_refuses_nonsense(level):
    assert bodykit_asset_code(CAR, level) is None


# -- inventory -----------------------------------------------------------
def test_inventory_reads_the_asset_series():
    i = inv()
    assert i.kits == (0, 1, 2, 3)
    assert i.hoods == ("0a", "1a", "1b", "2a", "2b", "3a", "3b")
    assert i.wings == i.hoods
    assert i.top_level == 3
    assert i.has_parts is True


def test_inventory_matches_case_insensitively():
    """The CDN publishes these lower-cased; a case-sensitive scan finds none."""
    assert inv().kits == (0, 1, 2, 3)
    upper = [c.upper() for c in CIVIC]
    assert CarBodyPartInventory.from_asset_codes(upper, CAR).kits == (0, 1, 2, 3)


def test_the_regular_shape_holds_for_both_observed_sizes():
    assert inv().shape_is_regular is True
    big = CarBodyPartInventory.from_asset_codes(S2000, BIG)
    assert big.top_level == 6
    assert len(big.hoods) == 13 == 1 + 2 * 6
    assert big.shape_is_regular is True


def test_an_irregular_shape_is_reported_not_assumed():
    thin = [c for c in CIVIC if "hood3" not in c]
    assert CarBodyPartInventory.from_asset_codes(thin, CAR).shape_is_regular is False


def test_inventory_is_empty_for_a_car_without_parts():
    i = CarBodyPartInventory.from_asset_codes(CIVIC, "McLaren_F1_1993")
    assert i.has_parts is False
    assert i.top_level is None and i.shape_is_regular is None


def test_inventory_ignores_unrelated_and_non_loda_assets():
    noise = CIVIC + ["Honda_CivicEGTNR_1995_Body_lodA_meshes",
                     "Honda_CivicEGTNR_1995_icon",
                     "Honda_CivicEGTNR_1995_Hood1a_loda_meshes",
                     "honda_civictypertnr_2017_hood1a_loda"]
    i = CarBodyPartInventory.from_asset_codes(noise, CAR)
    assert i.hoods == ("0a", "1a", "1b", "2a", "2b", "3a", "3b")
    assert i.kits == (0, 1, 2, 3)


# -- resolution: BODYKIT is unambiguous ----------------------------------
def test_bodykit_resolves_to_its_asset():
    out = resolve_body_parts({"BODYKIT": 2}, inv(), known_codes=CIVIC)
    sel = out["BODYKIT"]
    assert sel.status == "resolved_asset"
    assert sel.asset_code == "Honda_CivicEGTNR2_1995_loda"
    assert sel.kit_level == 2 and sel.resolved


def test_a_level_above_the_series_is_out_of_range():
    out = resolve_body_parts({"BODYKIT": 9}, inv(), known_codes=CIVIC)
    assert out["BODYKIT"].status == "level_out_of_range"
    assert out["BODYKIT"].asset_code is None


# -- HOOD / WING: a variant over the fitted kit --------------------------
def test_hood_selects_the_primary_or_secondary_of_the_fitted_kit():
    out = resolve_body_parts({"BODYKIT": 2, "HOOD": 0, "WING": 1}, inv(),
                             known_codes=CIVIC)
    assert out["HOOD"].status == "resolved_asset"
    assert out["HOOD"].asset_code == "Honda_CivicEGTNR_1995_Hood2a_loda"
    assert (out["HOOD"].kit_level, out["HOOD"].variant) == (2, "a")
    assert out["WING"].asset_code == "Honda_CivicEGTNR_1995_Wing2b_loda"
    assert out["WING"].variant == "b"


@pytest.mark.parametrize("level", [1, 2, 3])
@pytest.mark.parametrize("value,letter", [(0, "a"), (1, "b")])
def test_every_kit_level_admits_both_variants(level, value, letter):
    out = resolve_body_parts({"BODYKIT": level, "HOOD": value}, inv(),
                             known_codes=CIVIC)
    assert out["HOOD"].status == "resolved_asset"
    assert out["HOOD"].asset_code == (
        "Honda_CivicEGTNR_1995_Hood%d%s_loda" % (level, letter))


def test_a_stock_kit_resolves_to_the_level_zero_assets():
    """A kit-capable car ships a real level-0 kit, so this is not "stock".

    `stock` is reserved for a car with no kit assets at all, which is what
    all 29 live rows are.
    """
    out = resolve_body_parts({"BODYKIT": 0, "HOOD": 0, "WING": 0}, inv(),
                             known_codes=CIVIC)
    assert out["BODYKIT"].status == "resolved_asset"
    assert out["BODYKIT"].asset_code == "Honda_CivicEGTNR0_1995_loda"
    for slot in ("HOOD", "WING"):
        assert out[slot].status == "resolved_asset"
        assert out[slot].asset_code.endswith("%s0a_loda" % slot.title())
        assert out[slot].kit_level == 0
        assert out[slot].variant == "a"


@pytest.mark.parametrize("slot", ["HOOD", "WING"])
def test_a_secondary_with_no_kit_fitted_is_impossible(slot):
    """No car ships a `0b`, so there is nothing this could point at."""
    out = resolve_body_parts({"BODYKIT": 0, slot: 1}, inv(), known_codes=CIVIC)
    assert out[slot].status == "invalid_for_stock_kit"
    assert out[slot].asset_code is None
    assert out[slot].resolved is False


def test_no_car_ships_a_secondary_stock_part():
    """The asset-list fact the constraint rests on, asserted for both sizes."""
    for pool, car in ((CIVIC, CAR), (S2000, BIG)):
        i = CarBodyPartInventory.from_asset_codes(pool, car)
        assert "0a" in i.hoods and "0b" not in i.hoods
        assert "0a" in i.wings and "0b" not in i.wings


def test_the_option_count_is_derived_not_coincidental():
    """1 + 2K == K levels x 2 variants + 1 stock."""
    for pool, car, top in ((CIVIC, CAR, 3), (S2000, BIG, 6)):
        i = CarBodyPartInventory.from_asset_codes(pool, car)
        assert i.top_level == top
        assert len(i.hoods) == 1 + 2 * top


@pytest.mark.parametrize("value", [2, 3, 7, 12, -1])
def test_a_value_outside_the_variant_range_is_rejected(value):
    """An index into the option list would reach these; a variant cannot."""
    out = resolve_body_parts({"BODYKIT": 2, "HOOD": value}, inv(),
                             known_codes=CIVIC)
    assert out["HOOD"].status == "variant_out_of_range"
    assert out["HOOD"].asset_code is None


def test_both_variant_slots_behave_alike():
    assert VARIANT_SLOTS == {"HOOD", "WING"}
    out = resolve_body_parts({"BODYKIT": 3, "HOOD": 1, "WING": 1}, inv(),
                             known_codes=CIVIC)
    assert out["HOOD"].status == out["WING"].status == "resolved_asset"
    assert out["HOOD"].asset_code == "Honda_CivicEGTNR_1995_Hood3b_loda"
    assert out["WING"].asset_code == "Honda_CivicEGTNR_1995_Wing3b_loda"


def test_a_variant_cannot_be_read_without_the_kit_level():
    out = resolve_body_parts({"HOOD": 1}, inv(), known_codes=CIVIC)
    assert out["HOOD"].status == "bodykit_unknown"
    assert out["HOOD"].asset_code is None


def test_a_six_level_car_resolves_its_top_kit():
    big = CarBodyPartInventory.from_asset_codes(S2000, BIG)
    out = resolve_body_parts({"BODYKIT": 6, "HOOD": 1}, big, known_codes=S2000)
    assert out["BODYKIT"].asset_code == "Honda_S2000TNR6_2001_loda"
    assert out["HOOD"].asset_code == "Honda_S2000TNR_2001_Hood6b_loda"


# -- WHEELS is retired, not merely unresolved ---------------------------
def test_wheels_is_a_retired_slot():
    """Split into RIMS and TIRE; the key is vestigial and always 0."""
    assert RETIRED_SLOTS == {"WHEELS"}
    assert BODY_PART_SLOTS["WHEELS"] is None
    out = resolve_body_parts({"WHEELS": 0}, inv(), known_codes=CIVIC)
    assert out["WHEELS"].status == "retired_slot"
    assert out["WHEELS"].asset_code is None
    assert out["WHEELS"].value == 0
    assert out["WHEELS"].resolved is False


def test_wheels_stays_retired_even_with_a_value():
    """Nothing to resolve to, so a non-zero value is still not interpreted."""
    out = resolve_body_parts({"WHEELS": 3}, inv(), known_codes=CIVIC)
    assert out["WHEELS"].status == "retired_slot"
    assert out["WHEELS"].value == 3
    assert out["WHEELS"].asset_code is None


def test_wheels_is_reported_rather_than_dropped():
    """A caller must be able to tell "read and retired" from "never looked"."""
    out = resolve_body_parts({"BODYKIT": 0, "WHEELS": 0}, inv(), known_codes=CIVIC)
    assert "WHEELS" in out
    assert resolve_body_parts({"BODYKIT": 0}, inv(), known_codes=CIVIC).keys() == {"BODYKIT"}


# -- cars with no parts, and junk ---------------------------------------
def test_zero_on_a_car_without_parts_is_stock_not_a_failure():
    """27 of 29 live rows. Not every car has the kit system."""
    bare = CarBodyPartInventory.from_asset_codes(CIVIC, "McLaren_F1_1993")
    out = resolve_body_parts({"BODYKIT": 0, "HOOD": 0, "WING": 0, "WHEELS": 0}, bare)
    assert [out[s].status for s in ("BODYKIT", "HOOD", "WING")] == ["stock"] * 3
    assert out["WHEELS"].status == "retired_slot"


def test_nonzero_on_a_car_without_parts_is_flagged():
    bare = CarBodyPartInventory.from_asset_codes(CIVIC, "McLaren_F1_1993")
    out = resolve_body_parts({"BODYKIT": 2}, bare)
    assert out["BODYKIT"].status == "no_parts_for_car"


@pytest.mark.parametrize("value", ["1", None, 1.5, [], {}, True])
def test_non_integer_values_are_reported(value):
    out = resolve_body_parts({"BODYKIT": value}, inv(), known_codes=CIVIC)
    assert out["BODYKIT"].status == "non_integer_value"
    assert out["BODYKIT"].value is None


@pytest.mark.parametrize("setup", [None, 7, "x", [], ()])
def test_junk_setup_yields_nothing(setup):
    assert resolve_body_parts(setup, inv()) == {}


def test_absent_slots_are_omitted_not_invented():
    out = resolve_body_parts({"BODYKIT": 1}, inv(), known_codes=CIVIC)
    assert set(out) == {"BODYKIT"}


def test_unchecked_mode_returns_constructed_codes():
    """Without known_codes a code is built but not verified to exist."""
    out = resolve_body_parts({"BODYKIT": 2}, inv())
    assert out["BODYKIT"].asset_code == "Honda_CivicEGTNR2_1995_loda"
