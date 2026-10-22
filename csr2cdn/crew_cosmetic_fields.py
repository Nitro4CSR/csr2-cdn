"""Roster cosmetic fields beyond the twelve-slot appearance block.

A crew roster row carries two further cosmetic objects that the appearance
decoder never looked at, both present on live rosters:

``car_tnr_setup``
    Seven Tuner Stars slots, on every row: ``RIMS``, ``TIRE``, ``BOOST_COLOR``,
    ``BODYKIT``, ``HOOD``, ``WING``, ``WHEELS``. Three have libraries, and they
    are exactly the Tuner Stars libraries that had no reader --
    ``CarTunerStarsRimLibrary`` names the wheel (``1000007`` is "3B",
    ``1000200`` is "84A"), ``CarTunerStarsTireLibrary`` the tyre,
    ``CarTunerStarsBoostColorLibrary`` the boost colour. The remaining four are
    aftermarket body parts with no library located yet, so they are reported as
    raw values rather than guessed at.

``car_gacha_config``
    A complete alternative cosmetic set applied by a gacha roll, keyed by
    abbreviation: ``paid`` paint, ``inid`` interior, ``caid`` calliper,
    ``livid`` livery, ``lzsid`` livery zone mask, ``whbn`` wheel bundle name.
    These mirror the ``GachaConfigs`` entries inside the car's own bundle, which
    is what lets a gacha paint extend the paint index space: the Porsche
    reporting paint index 10 into a 10-entry list has
    ``car_gacha_config.paid == 2694``, the exact ID that fills position 10.

Unset fields use ``INT32_MIN`` or ``INT32_MAX`` rather than 0 or absence.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Tuple

from csr2cdn.car_visuals_data import UNSET_VALUES, match_library

#: Tuner Stars setup key -> the library slot naming it, or ``None`` if unknown.
TNR_SETUP_SLOTS: Mapping[str, Optional[str]] = {
    "RIMS": "tuner_rim",
    "TIRE": "tire",
    "BOOST_COLOR": "boost_color",
    # Aftermarket body parts. Their values are small ordinals (BODYKIT 6 was
    # observed) and no shipped library carries them, so they stay unlabelled.
    "BODYKIT": None,
    "HOOD": None,
    "WING": None,
    "WHEELS": None,
}

#: Gacha config key -> roster slot it corresponds to.
GACHA_CONFIG_SLOTS: Mapping[str, str] = {
    "paid": "paint",
    "inid": "interior",
    "caid": "calliper",
    "livid": "livery",
    "lzsid": "livery_zones_set",
    "whbn": "wheel",
}

#: Gacha keys carrying a global library ID rather than an index or a name.
GACHA_ID_KEYS = frozenset({"paid", "inid", "caid", "livid", "lzsid"})

_MAX_SLOTS = 64


def _clean_int(value: Any) -> Optional[int]:
    if type(value) is not int or value in UNSET_VALUES:
        return None
    return value


@dataclass(frozen=True)
class CosmeticValue:
    """One cosmetic field: what the wire said, and what it names."""

    key: str
    value: Any = field(repr=False)
    slot: Optional[str] = None
    name: Optional[str] = field(default=None, repr=False)
    status: str = "unresolved"

    @property
    def resolved(self) -> bool:
        return self.name is not None


@dataclass(frozen=True)
class TunerStarsSetup:
    """The ``car_tnr_setup`` block, resolved where a library exists."""

    slots: Mapping[str, CosmeticValue] = field(default_factory=dict, repr=False)

    def __getattr__(self, name: str) -> CosmeticValue:
        key = name.upper()
        slots = object.__getattribute__(self, "slots")
        if key in slots:
            return slots[key]
        raise AttributeError(name)

    @property
    def present(self) -> Tuple[str, ...]:
        """Keys whose value is set and not a default of zero."""
        return tuple(k for k, v in self.slots.items()
                     if _clean_int(v.value) not in (None, 0))

    @classmethod
    def from_wire(cls, raw: Any, library: Any = None,
                  model_key: Optional[str] = None) -> Optional["TunerStarsSetup"]:
        if not isinstance(raw, Mapping) or not raw or len(raw) > _MAX_SLOTS:
            return None
        slots = {}
        for key, value in raw.items():
            if not isinstance(key, str):
                continue
            slot = TNR_SETUP_SLOTS.get(key)
            number = _clean_int(value)
            if number is None:
                slots[key] = CosmeticValue(key, value, slot, None, "unset")
                continue
            if slot is None:
                slots[key] = CosmeticValue(key, number, None, None, "no_library_known")
                continue
            match = match_library(library, model_key, slot, number)
            if match is not None:
                status = "resolved"
            elif number == 0:
                # The Tuner Stars rim and boost-colour libraries start at
                # 1,000,001, so a 0 from a car with no Tuner Stars part fitted
                # is "stock", not a lookup failure. 27 of 29 live rows are this.
                status = "none_or_stock"
            else:
                status = "id_not_in_library"
            slots[key] = CosmeticValue(
                key, number, slot, match.name if match is not None else None, status)
        return cls(slots) if slots else None


@dataclass(frozen=True)
class GachaSelection:
    """The ``car_gacha_config`` block: a full cosmetic set from a gacha roll."""

    slots: Mapping[str, CosmeticValue] = field(default_factory=dict, repr=False)

    def __getattr__(self, name: str) -> CosmeticValue:
        slots = object.__getattribute__(self, "slots")
        for key, value in slots.items():
            if GACHA_CONFIG_SLOTS.get(key) == name or key == name:
                return value
        raise AttributeError(name)

    @property
    def applied(self) -> bool:
        """True when the roll set at least one cosmetic."""
        return any(v.status != "unset" for v in self.slots.values())

    @classmethod
    def from_wire(cls, raw: Any, library: Any = None,
                  model_key: Optional[str] = None) -> Optional["GachaSelection"]:
        if not isinstance(raw, Mapping) or not raw or len(raw) > _MAX_SLOTS:
            return None
        slots = {}
        for key, value in raw.items():
            if not isinstance(key, str):
                continue
            slot = GACHA_CONFIG_SLOTS.get(key)
            if key in GACHA_ID_KEYS:
                number = _clean_int(value)
                if number is None:
                    slots[key] = CosmeticValue(key, value, slot, None, "unset")
                    continue
                match = match_library(library, model_key, slot, number) if slot else None
                slots[key] = CosmeticValue(
                    key, number, slot, match.name if match is not None else None,
                    "resolved" if match is not None else "id_not_in_library")
            elif isinstance(value, str) and value and value != "-1":
                # whbn is a wheel bundle name, already its own identifier.
                slots[key] = CosmeticValue(key, value, slot, value, "resolved_name")
            else:
                slots[key] = CosmeticValue(key, value, slot, None, "unset")
        return cls(slots) if slots else None


def resolve_extra_cosmetics(extras: Any, library: Any = None,
                            model_key: Optional[str] = None) -> dict:
    """Resolve both extra cosmetic blocks from a roster row's ``extras``."""
    if not isinstance(extras, Mapping):
        return {"tuner_stars": None, "gacha": None}
    return {
        "tuner_stars": TunerStarsSetup.from_wire(
            extras.get("car_tnr_setup"), library, model_key),
        "gacha": GachaSelection.from_wire(
            extras.get("car_gacha_config"), library, model_key),
    }


__all__ = [
    "GACHA_CONFIG_SLOTS",
    "GACHA_ID_KEYS",
    "TNR_SETUP_SLOTS",
    "CosmeticValue",
    "GachaSelection",
    "TunerStarsSetup",
    "resolve_extra_cosmetics",
]
