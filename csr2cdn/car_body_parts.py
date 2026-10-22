"""Tuner Stars body parts: the four upper-case ``car_tnr_setup`` slots.

``car_tnr_setup`` carries seven keys. Three resolve against libraries with real
names (``RIMS``, ``TIRE``, ``BOOST_COLOR``; see ``crew_cosmetic_fields``). The
other four -- ``BODYKIT``, ``HOOD``, ``WING``, ``WHEELS`` -- are integers that
select *per-car* geometry, and this module maps them onto the CDN asset codes
that hold it.

Why there is no library and no name
-----------------------------------
There is no name to look up. ``Localisation_FlatBuffer_EN`` holds 22,048
``TEXT_`` keys and not one of them embeds a kit, hood or wing index; the only
kit strings are UI chrome (``TEXT_BODYKIT_BUTTON`` -> "BODYKITS",
``TEXT_HOOD_BUTTON`` -> "HOODS") and tutorial copy. The game identifies these
parts by index and shows them as numbered thumbnails, so a part's only stable
identifier is its asset code. That is what this module returns.

The asset naming, verified against the live asset list
------------------------------------------------------
For a model key ``{stem}_{year}``::

    BODYKIT level N  ->  {stem}N_{year}_loda
    HOOD    N, v     ->  {stem}_{year}_Hood{N}{v}_loda     v in "ab"
    WING    N, v     ->  {stem}_{year}_Wing{N}{v}_loda

25 cars ship the full kits+hoods+wings triple and **all 25 are TNR models**.
The shape is uniform: kit levels ``0..K`` with ``K`` either 3 or 6, and
``1 + 2K`` hood and wing options -- ``0a`` for stock, then ``{N}a`` and
``{N}b`` for each level above it. That matches the tutorial copy exactly:
"Each kit comes with a secondary Hood option to fit."

No kit car has a ``_common`` bundle, so unlike the dev82 cosmetics there is no
``CarVisualsData`` list to compose; the asset list is the ground truth.

How HOOD and WING are read
--------------------------
They are a **variant selector over the fitted kit**, not an index into the
car's option list::

    HOOD = 0  ->  {stem}_{year}_Hood{BODYKIT}a_loda   (primary)
    HOOD = 1  ->  {stem}_{year}_Hood{BODYKIT}b_loda   (secondary)

The game constrains them to ``{0, 1}``, and both are forced to ``0`` while
``BODYKIT`` is ``0``; only a kit at level 1 or above admits a ``1``. That
constraint refutes the competing reading outright: an index into the option
list would range over ``0..2K``, not ``{0, 1}``.

The asset list corroborates it independently -- **no car ships a ``0b``** --
and under this reading that absence is exactly *why* a stock kit forces ``0``.
It also turns the ``1 + 2K`` option count from a coincidence into a
derivation: K kit levels times two variants, plus one stock option. The
tutorial copy says the same thing in words: "Each kit comes with a secondary
Hood option to fit."

Violations of the constraint are reported rather than resolved:
``variant_out_of_range`` for a value outside ``{0, 1}``, and
``invalid_for_stock_kit`` for a secondary requested with no kit fitted, which
is the case that has no asset to point at.

``WHEELS`` is a **retired slot**. It was split into ``RIMS`` and ``TIRE``,
both of which resolve against their own libraries in ``crew_cosmetic_fields``,
and the key is vestigial: the service still sends it and the game still has a
``TEXT_WHEELS_BUTTON`` tab, but nothing drives it. Every piece of evidence
agrees -- no ``Wheel``-suffixed ``_loda`` asset exists for any car, and all 29
sampled rows report ``0``. It is reported as ``retired_slot`` and never
resolved, because there is nothing left for it to resolve to.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple

#: Upper-case ``car_tnr_setup`` keys handled here, mapped to their asset token.
#: ``WHEELS`` is present with no token because the slot is deliberately
#: unresolved rather than silently dropped.
BODY_PART_SLOTS: Dict[str, Optional[str]] = {
    "BODYKIT": "",      # the level goes into the model stem, not a suffix
    "HOOD": "Hood",
    "WING": "Wing",
    "WHEELS": None,     # retired; split into RIMS and TIRE
}
#: Slots the game no longer drives. Still sent by the service, always ``0``.
RETIRED_SLOTS = frozenset({"WHEELS"})
#: Slots whose integer selects the primary/secondary variant of the fitted
#: kit. Bounded to ``{0, 1}``, and forced to ``0`` when ``BODYKIT`` is ``0``.
VARIANT_SLOTS = frozenset({"HOOD", "WING"})
#: Variant letters a kit level ships, in order: primary then secondary.
PART_VARIANTS = ("a", "b")
#: Kit-level counts observed across all 25 kit-capable cars.
OBSERVED_TOP_LEVELS = (3, 6)

_MODEL_RE = re.compile(r"^(?P<stem>.+)_(?P<year>\d{4})$")


def split_model_key(model_key: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """``"Honda_CivicEGTNR_1995"`` -> ``("Honda_CivicEGTNR", "1995")``."""
    if not isinstance(model_key, str):
        return (None, None)
    match = _MODEL_RE.match(model_key)
    return (match.group("stem"), match.group("year")) if match else (None, None)


def bodykit_asset_code(model_key: Optional[str], level: int) -> Optional[str]:
    """The kit level is spliced into the stem, before the year."""
    stem, year = split_model_key(model_key)
    if stem is None or not isinstance(level, int) or isinstance(level, bool) or level < 0:
        return None
    return "%s%d_%s_loda" % (stem, level, year)


def part_asset_code(model_key: Optional[str], slot: str, level: int,
                    variant: str = "a") -> Optional[str]:
    """Asset code for a hood or wing at ``level`` with variant ``a``/``b``."""
    token = BODY_PART_SLOTS.get(slot)
    if not token or variant not in PART_VARIANTS:
        return None
    stem, year = split_model_key(model_key)
    if stem is None or not isinstance(level, int) or isinstance(level, bool) or level < 0:
        return None
    return "%s_%s_%s%d%s_loda" % (stem, year, token, level, variant)


@dataclass(frozen=True)
class CarBodyPartInventory:
    """Which parts a car actually ships, read off the CDN asset list.

    ``hoods`` and ``wings`` hold ``"0a"``-style tokens in sorted order, which
    is the order the ``POSITION`` reading would index.
    """
    model_key: Optional[str] = None
    kits: Tuple[int, ...] = ()
    hoods: Tuple[str, ...] = ()
    wings: Tuple[str, ...] = ()

    @property
    def has_parts(self) -> bool:
        return bool(self.kits or self.hoods or self.wings)

    @property
    def top_level(self) -> Optional[int]:
        return max(self.kits) if self.kits else None

    @property
    def shape_is_regular(self) -> Optional[bool]:
        """True when the car has ``1 + 2K`` hoods and wings for ``K`` kits.

        Every one of the 25 kit-capable cars satisfies this. A False here
        means the assumption has broken for a newly shipped car.
        """
        top = self.top_level
        if top is None or not self.hoods:
            return None
        expected = 1 + 2 * top
        return len(self.hoods) == expected and len(self.wings) == expected

    def options(self, slot: str) -> Tuple[str, ...]:
        return {"HOOD": self.hoods, "WING": self.wings}.get(slot, ())

    @classmethod
    def from_asset_codes(cls, codes: Iterable[str],
                         model_key: Optional[str]) -> "CarBodyPartInventory":
        """Scan a flat list of CDN asset codes. Matching is case-insensitive.

        Kit-car assets are published lower-cased, so a case-sensitive lookup
        finds nothing; that cost us a full validation pass once already.
        """
        stem, year = split_model_key(model_key)
        if stem is None:
            return cls(model_key)
        stem_l, kits = stem.lower(), set()
        hoods, wings = set(), set()
        kit_re = re.compile(r"^%s(\d+)_%s_loda$" % (re.escape(stem_l), re.escape(year)))
        hood_re = re.compile(r"^%s_%s_hood(\d+[a-z]?)_loda$"
                             % (re.escape(stem_l), re.escape(year)))
        wing_re = re.compile(r"^%s_%s_wing(\d+[a-z]?)_loda$"
                             % (re.escape(stem_l), re.escape(year)))
        for code in codes:
            low = str(code).lower()
            if not low.endswith("_loda"):
                continue
            match = kit_re.match(low)
            if match:
                kits.add(int(match.group(1)))
                continue
            match = hood_re.match(low)
            if match:
                hoods.add(match.group(1))
                continue
            match = wing_re.match(low)
            if match:
                wings.add(match.group(1))
        return cls(model_key, tuple(sorted(kits)),
                   tuple(sorted(hoods, key=_option_sort)),
                   tuple(sorted(wings, key=_option_sort)))


def _option_sort(token: str) -> Tuple[int, str]:
    match = re.match(r"^(\d+)([a-z]?)$", token)
    return (int(match.group(1)), match.group(2)) if match else (10 ** 6, token)


@dataclass(frozen=True)
class BodyPartSelection:
    """One resolved ``car_tnr_setup`` body-part slot."""
    slot: str
    value: Optional[int] = None
    status: str = "unknown"
    asset_code: Optional[str] = None
    #: The kit level the part belongs to; for HOOD/WING this is the BODYKIT
    #: level, since the variant is read against the fitted kit.
    kit_level: Optional[int] = None
    #: ``"a"`` primary or ``"b"`` secondary, for HOOD/WING.
    variant: Optional[str] = None

    @property
    def resolved(self) -> bool:
        return self.status in ("resolved_asset", "stock")


def resolve_body_parts(setup: Any, inventory: CarBodyPartInventory,
                       *, known_codes: Optional[Iterable[str]] = None
                       ) -> Dict[str, BodyPartSelection]:
    """Resolve the four body-part slots of one ``car_tnr_setup`` mapping.

    ``known_codes`` optionally bounds the result to assets that really exist;
    without it a constructed code is returned unchecked.
    """
    if not isinstance(setup, Mapping):
        return {}
    have = {str(c).lower() for c in known_codes} if known_codes is not None else None

    def exists(code: Optional[str]) -> bool:
        return code is not None and (have is None or code.lower() in have)

    out: Dict[str, BodyPartSelection] = {}
    level = setup.get("BODYKIT")
    level = level if isinstance(level, int) and not isinstance(level, bool) else None

    for slot in BODY_PART_SLOTS:
        if slot not in setup:
            continue
        raw = setup[slot]
        if not isinstance(raw, int) or isinstance(raw, bool):
            out[slot] = BodyPartSelection(slot, None, "non_integer_value")
            continue
        if slot in RETIRED_SLOTS:
            # Superseded by RIMS and TIRE. Reported so a caller sees the key
            # was read and deliberately not resolved, rather than missed.
            out[slot] = BodyPartSelection(slot, raw, "retired_slot")
            continue
        if not inventory.has_parts:
            out[slot] = BodyPartSelection(
                slot, raw, "stock" if raw == 0 else "no_parts_for_car")
            continue

        if slot == "BODYKIT":
            code = bodykit_asset_code(inventory.model_key, raw)
            if raw in inventory.kits and exists(code):
                out[slot] = BodyPartSelection(slot, raw, "resolved_asset", code,
                                              kit_level=raw)
            elif raw == 0:
                out[slot] = BodyPartSelection(slot, raw, "stock", kit_level=0)
            else:
                out[slot] = BodyPartSelection(slot, raw, "level_out_of_range",
                                              kit_level=raw)
            continue

        # HOOD / WING: a variant selector over the fitted kit.
        if raw not in range(len(PART_VARIANTS)):
            out[slot] = BodyPartSelection(slot, raw, "variant_out_of_range")
            continue
        if level is None:
            out[slot] = BodyPartSelection(slot, raw, "bodykit_unknown")
            continue
        if level == 0 and raw != 0:
            # No car ships a `0b`, so there is nothing this could point at.
            out[slot] = BodyPartSelection(slot, raw, "invalid_for_stock_kit",
                                          kit_level=0)
            continue
        letter = PART_VARIANTS[raw]
        code = part_asset_code(inventory.model_key, slot, level, letter)
        if exists(code):
            out[slot] = BodyPartSelection(slot, raw, "resolved_asset", code,
                                          level, letter)
        else:
            out[slot] = BodyPartSelection(
                slot, raw, "stock" if (level == 0 and raw == 0) else "asset_missing",
                None, level, letter)
    return out
