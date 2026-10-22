"""Per-car cosmetic index spaces from the public ``<crdb>_common`` asset bundle.

Why this exists
---------------
A crew roster row reports a car's cosmetics as small integers --
``car_paint_id`` of ``0`` or ``15`` -- and those numbers are *not* global
library IDs. ``CarPaintLibrary`` numbers paints from 1 to 3114, so ``0`` cannot
be an ID at all, and ``15`` names a paint no Mustang can wear.

They are positions in a per-car list. Each car ships a ``CarVisualsData``
behaviour inside its ``<crdb>_common`` bundle holding the cosmetics it starts
with, and an unlockables behaviour holding everything it can earn. Concatenate
the two, in order, dropping repeats, and the roster's number is an index into
the result::

    valid(slot) = dedup( CarVisualsData.<Slot>IDs + flatten(AllUnlockables.<slot>IDs) )

The unlockable lists are ragged arrays flattened into one Unity list, with
``-1`` (or the string ``"-1"`` for wheel names) terminating each milestone
group; the sentinels are separators, not entries, so they are dropped before
indexing.

Worked example, ``Ford_Mustang302_1970`` (database 34049): defaults
``[1156, 451, 1159, 1160]`` then ten groups of three unlockables compose a
30-entry space in which index ``0`` is paint ``1156`` "Ford Calypso Coral" and
index ``15`` is paint ``1323`` "Ford Dark Highland Green".

Which slots are indexed
-----------------------
**Only ``paint``.** This was established against a live 29-row crew roster, not
assumed: for every car on it, the wire paint value was absent from that car's
own ID list (0/14) while reading it as a position produced a paint of the car's
own marque. On ``Ford_Mustang302_1970``, paint ``2`` as an index is ``1159``
"Ford Grabber Orange"; read as an ID it is "Volkswagen Reflex Silver".

``interior``, ``calliper``, ``livery_zones_set`` and ``livery`` carry **global
library IDs**. The same roster shows their wire values landing inside the car's
own list as members rather than positions (calliper 14/14, interior 13/14) and
resolving in their libraries 100% of the time. For these slots the per-car list
is an *eligibility set* -- which cosmetics that car may wear -- so it validates
a value without relocating it. Mustang interior ``66`` is "Ford Ebony" and sits
first in the car's interior list.

That asymmetry matches the binary: the native code carries a
``CurrentPaintIndex`` and a paint list that grows, and nothing equivalent for
any other slot. The wire key ``car_paint_id`` is simply misnamed.

``wheel`` carries a model-prefixed bundle name, ``{model_key}_{BundleName}``,
e.g. ``Ford_Mustang302_1970_Wheel1A_3D``; the bundle lists the unprefixed
``Wheel1A_3D``, so the prefix is stripped before matching.

Tuner Stars cosmetics occupy a separate ID space from 1,000,001 up and are
always global IDs, including for paint, so a paint value at or above
:data:`TNR_ID_FLOOR` is never treated as an index.

Decoding needs UnityPy (``pip install csr2-cdn[images]``). Composition needs
nothing, so a decoded bundle can be composed anywhere.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
import io
from typing import Any, Iterable, Mapping, Optional, Sequence, Tuple, Union

from csr2cdn.errors import Csr2CdnError

#: Separator that terminates each milestone group in an unlockable list.
SENTINEL = -1
#: The wheel list is a string list, so its separator is the string form.
WHEEL_SENTINEL = "-1"

#: Tuner Stars cosmetics live in their own ID space and are never indices.
TNR_ID_FLOOR = 1_000_000

#: "Unset" markers seen in bundle and metadata cosmetic fields.
#:
#: ``CarVisualsGachaConfig`` pads unused slots with ``INT32_MAX`` -- every
#: ``WrapPaintID`` on the sampled cars is exactly that -- and the metadata's
#: livery-zone overrides use ``INT32_MIN``. Neither is a cosmetic ID.
INT32_MAX = 2_147_483_647
INT32_MIN = -2_147_483_648
UNSET_VALUES = (INT32_MAX, INT32_MIN)

#: slot -> the ``GachaConfigs`` entry key contributing to it.
#:
#: A car's gacha configurations name cosmetics beyond the shipped and unlockable
#: lists, and for paint they extend the index space itself: the live roster had
#: one car reporting index 10 into a 10-entry public list, which its first gacha
#: paint fills exactly.
GACHA_SLOT_KEYS: Mapping[str, str] = {
    "paint": "PaintID",
    "interior": "InteriorID",
    "calliper": "CalliperID",
    "livery_zones_set": "LiveryZonesSetID",
    "wheel": "WheelBundleName",
}

#: Prefix of the per-car mesh anchors a racing number can be placed on.
#:
#: ``CarVisuals.GetNumberZonesCount`` returns the length of the car's
#: ``RacingNumberGO`` collection and ``ApplyNumberZoneToMeshes`` applies one;
#: bundles that ship them always ship exactly three. The customisation UI
#: exposes no zone choice, so this machinery is internal.
NUMBER_ZONE_ANCHOR = "RacingNumber"
NUMBER_ZONE_ANCHORS_PER_CAR = 3

#: Slots selecting one of the car's number anchors, with 0 meaning none.
#:
#: ``car_decal_number_zone_id`` is ``AppliedNumberZoneID`` in the metadata. The
#: customisation UI only lets a player show or hide the racing number, so 0 and
#: 1 behave as a toggle in practice -- but a live roster row reports 3, which no
#: boolean produces and which matches the third of the car's three
#: ``RacingNumber`` anchors. It is therefore read as a selector where 0 means
#: hidden, bounded by the anchor count when that is known. Only 1 and 3 have
#: been observed, so whether every anchor is reachable from the UI is unsettled.
PLACEMENT_SLOTS = frozenset({"decal_number_zone"})
FLAG_SLOTS = PLACEMENT_SLOTS

#: slot -> (CarVisualsData defaults key, AllUnlockables key, sentinel)
#:
#: Every slot here has a per-car list in the bundle. What the list *means*
#: differs by slot: see INDEX_SLOTS and ELIGIBILITY_SLOTS.
CAR_LIST_SLOTS: Mapping[str, Tuple[str, str, Union[int, str]]] = {
    "paint": ("CarPaintIDs", "carPaintIDs", SENTINEL),
    "interior": ("CarInteriorIDs", "carInteriorIDs", SENTINEL),
    "calliper": ("CarCalliperIDs", "carCalliperIDs", SENTINEL),
    # These two keys name different libraries despite their spelling:
    # CarVisualsData.CarLiveryZonesSetIDs holds zone masks, while
    # AllUnlockables.carLiverySetIDs holds per-car livery sets. Merging them
    # produced a list mixing two ID spaces, so each gets its own slot and
    # neither borrows the other's unlockables.
    "livery_zones_set": ("CarLiveryZonesSetIDs", None, SENTINEL),
    "livery_set": (None, "carLiverySetIDs", SENTINEL),
    "wheel": ("WheelBundleNames", "wheelBundleNames", WHEEL_SENTINEL),
}

#: Backwards-compatible alias. Prefer CAR_LIST_SLOTS: having a list does not
#: make a slot indexed, which is the mistake this name invites.
INDEXED_SLOTS = CAR_LIST_SLOTS

#: The only slot whose wire value is a position in the car's list.
INDEX_SLOTS = frozenset({"paint"})

#: The roster slot carrying a model-prefixed bundle name rather than a number.
NAME_SLOTS = frozenset({"wheel"})

#: Slots whose per-car list says which values are *allowed*, not where they are.
ELIGIBILITY_SLOTS = frozenset(
    {"interior", "calliper", "livery_zones_set", "livery_set"})

#: No slot uses 0 as "nothing applied".
#:
#: An earlier reading treated ``livery_zones_set`` 0 that way, on the strength
#: of a wrong library. Against ``LiveryZonesSetLibrary`` 0 is "FULL BODY", a
#: perfectly ordinary selection, and the real unset marker is ``INT32_MIN``,
#: which the roster sends on ten of thirty rows.
ZERO_MEANS_NONE: frozenset = frozenset()

#: Roster slot -> the library slot names to try, in order.
#:
#: The decoded libraries use their own vocabulary, which does not match the
#: roster's for several slots. ``CarLiverySetLibrary`` labels its records
#: ``livery_set`` while the roster field is ``car_liveryZonesSet_id``; both
#: number-decal colour fields are served by the eleven-entry
#: ``CarColorLibrary``, whose records are labelled ``color``; and Tuner Stars
#: rim names live under ``tuner_rim``. These mismatches, not missing data, are
#: why those joins were previously recorded as unverified.
LIBRARY_SLOT_ALIASES: Mapping[str, Tuple[str, ...]] = {
    # car_liveryZonesSet_id selects a shader zone MASK, served by
    # LiveryZonesSetLibrary. CarLiverySetLibrary is a different thing -- 637
    # per-car livery sets -- and resolving against it put Ferrari livery names
    # on Mustangs and Porsches. Every roster value observed (0, 9, 15) is a
    # mask: FULL BODY, CONTRAST, ACCENT.
    "livery_zones_set": ("livery_zones_set", "livery_zone_mask"),
    "livery_set": ("livery_set",),
    "decal_number_color": ("decal_number_color", "color"),
    "decal_number_shape_color": ("decal_number_shape_color", "color"),
    "wheel": ("wheel", "tuner_rim"),
}


def library_slots(slot: str) -> Tuple[str, ...]:
    """The library slot names that may hold labels for a roster slot."""
    return LIBRARY_SLOT_ALIASES.get(slot, (slot,))


def match_library(library: Any, model_key: Optional[str], slot: str, code: Any) -> Any:
    """Look a code up under every library slot name this roster slot can use.

    Tried in order: this car's own records, then the global ``*`` records, then
    any car's record for the same code. That last pass matters because some
    library records are bound to one specific model -- the decoder reads a
    per-ID *exclusion* list as a binding -- so a live roster car can wear a
    cosmetic whose only record names a different car. Interior ``1000133`` is
    recorded against ``Toyota_GRSupraTNR_2020`` and was worn by a
    ``Toyota_SupraMK4TNR_1994``. The label belongs to the ID, so it is correct
    either way; only eligibility is model-specific, and that is answered by the
    car's own lists rather than here.
    """
    if library is None:
        return None
    for candidate in library_slots(slot):
        found = library.match(model_key, candidate, code)
        if found is not None:
            return found
    wanted = set(library_slots(slot))
    for record in getattr(library, "records", ()):
        if record.slot in wanted and type(record.code) is type(code) and record.code == code:
            return record
    return None

#: Marker keys identifying the two behaviours inside a ``_common`` bundle.
_VISUALS_MARKER = "CarPaintIDs"
_UNLOCKABLES_MARKER = "AllUnlockables"

_MAX_BUNDLE_BYTES = 64 * 1024 * 1024
_MAX_LIST = 4096


class CarVisualsError(Csr2CdnError):
    """A ``_common`` bundle could not be decoded into a usable index space."""


def _is_sentinel(value: Any, sentinel: Union[int, str]) -> bool:
    return value == sentinel or (isinstance(value, str) and value == str(sentinel))


def split_groups(flat: Optional[Sequence[Any]],
                 sentinel: Union[int, str] = SENTINEL) -> Tuple[Tuple[Any, ...], ...]:
    """Split one flattened unlockable list back into its milestone groups.

    Trailing and repeated sentinels produce no empty groups, and a list with no
    sentinel at all is a single group.
    """
    if not flat:
        return ()
    if len(flat) > _MAX_LIST:
        raise CarVisualsError("unlockable list is implausibly long")
    groups, current = [], []
    for value in flat:
        if _is_sentinel(value, sentinel):
            if current:
                groups.append(tuple(current))
                current = []
        else:
            current.append(value)
    if current:
        groups.append(tuple(current))
    return tuple(groups)


def compose_valid_ids(defaults: Optional[Sequence[Any]],
                      unlockables: Optional[Sequence[Any]],
                      sentinel: Union[int, str] = SENTINEL) -> Tuple[Any, ...]:
    """Build one slot's index space: defaults first, then unseen unlockables.

    Order is what makes the index meaningful, so it is preserved exactly;
    repeats are dropped because the game keeps one entry per cosmetic.
    """
    seen, out = set(), []
    for value in list(defaults or []):
        if _is_sentinel(value, sentinel) or value in seen:
            continue
        seen.add(value)
        out.append(value)
    for group in split_groups(unlockables, sentinel):
        for value in group:
            if value in seen:
                continue
            seen.add(value)
            out.append(value)
    return tuple(out)


def gacha_values(configs: Any, key: str) -> Tuple[Any, ...]:
    """Cosmetic values a car's gacha configurations name for one slot, in order."""
    out = []
    if not isinstance(configs, Sequence) or isinstance(configs, (str, bytes)):
        return ()
    for entry in configs[:_MAX_LIST]:
        if not isinstance(entry, Mapping):
            continue
        value = entry.get(key)
        if value is None or value in UNSET_VALUES:
            continue
        if isinstance(value, str) and (not value or value == WHEEL_SENTINEL):
            continue
        if value not in out:
            out.append(value)
    return tuple(out)


@dataclass(frozen=True)
class CarVisualIndexSpace:
    """The ordered cosmetic lists a single car's roster indices address."""

    model_key: str
    valid: Mapping[str, Tuple[Any, ...]] = field(repr=False)
    defaults: Mapping[str, Tuple[Any, ...]] = field(default_factory=dict, repr=False)
    unlock_groups: Mapping[str, Tuple[Tuple[Any, ...], ...]] = field(default_factory=dict, repr=False)
    gacha: Mapping[str, Tuple[Any, ...]] = field(default_factory=dict, repr=False)
    lock_paints_to_index: Optional[int] = None
    has_own_livery: Optional[bool] = None
    gacha_config_count: Optional[int] = None
    number_zone_count: Optional[int] = None
    database_version: Optional[str] = None
    asset_version: Optional[str] = None

    def length(self, slot: str) -> int:
        return len(self.valid.get(slot, ()))

    def resolve_index(self, slot: str, index: Any) -> Optional[Any]:
        """The global ID at *index*, or ``None`` if out of range.

        Meaningful for :data:`INDEX_SLOTS`; for other slots the list is an
        eligibility set and a position in it carries no meaning.
        """
        if slot not in CAR_LIST_SLOTS or not isinstance(index, int) or isinstance(index, bool):
            return None
        entries = self.valid.get(slot, ())
        return entries[index] if 0 <= index < len(entries) else None

    def index_of(self, slot: str, code: Any) -> Optional[int]:
        """The index a given global ID or wheel name occupies, if present."""
        entries = self.valid.get(slot, ())
        try:
            return entries.index(code)
        except ValueError:
            return None

    def contains(self, slot: str, code: Any) -> bool:
        return code in self.valid.get(slot, ())

    @property
    def paints_locked(self) -> bool:
        """True when the car restricts selection to its shipped defaults.

        Observed values are exactly ``0`` or ``len(defaults)`` across sampled
        cars, so this reads as a flag rather than an arbitrary bound.
        """
        lock = self.lock_paints_to_index
        return bool(lock) and lock == len(self.defaults.get("paint", ()))

    def as_dict(self) -> dict:
        return {
            "model_key": self.model_key,
            "database_version": self.database_version,
            "asset_version": self.asset_version,
            "lock_paints_to_index": self.lock_paints_to_index,
            "paints_locked": self.paints_locked,
            "has_own_livery": self.has_own_livery,
            "gacha_config_count": self.gacha_config_count,
            "number_zone_count": self.number_zone_count,
            "gacha": {slot: list(values) for slot, values in self.gacha.items()},
            "lengths": {slot: self.length(slot) for slot in CAR_LIST_SLOTS},
            "valid": {slot: list(values) for slot, values in self.valid.items()},
        }


def compose_index_space(model_key: str, visuals: Mapping[str, Any],
                        unlockables: Optional[Mapping[str, Any]] = None, *,
                        database_version: Optional[str] = None,
                        asset_version: Optional[str] = None) -> CarVisualIndexSpace:
    """Build an index space from two already-decoded Unity type trees."""
    if not isinstance(model_key, str) or not model_key:
        raise CarVisualsError("a model key is required")
    if not isinstance(visuals, Mapping) or _VISUALS_MARKER not in visuals:
        raise CarVisualsError("CarVisualsData tree missing %r" % _VISUALS_MARKER)
    pool = unlockables.get(_UNLOCKABLES_MARKER) if isinstance(unlockables, Mapping) else None
    if pool is not None and not isinstance(pool, Mapping):
        raise CarVisualsError("AllUnlockables must be an object")

    configs = visuals.get("GachaConfigs")
    valid, defaults, groups, gacha = {}, {}, {}, {}
    for slot, (default_key, unlock_key, sentinel) in CAR_LIST_SLOTS.items():
        shipped = (visuals.get(default_key) or ()) if default_key else ()
        earned = ((pool.get(unlock_key) if pool else None) or ()) if unlock_key else ()
        if not isinstance(shipped, Sequence) or isinstance(shipped, (str, bytes)):
            raise CarVisualsError("%s must be a list" % default_key)
        defaults[slot] = tuple(v for v in shipped if not _is_sentinel(v, sentinel))
        groups[slot] = split_groups(earned, sentinel)
        composed = list(compose_valid_ids(shipped, earned, sentinel))
        gacha[slot] = (gacha_values(configs, GACHA_SLOT_KEYS[slot])
                       if slot in GACHA_SLOT_KEYS else ())
        # Gacha cosmetics come last, so existing indices keep their meaning.
        for value in gacha[slot]:
            if value not in composed:
                composed.append(value)
        valid[slot] = tuple(composed)

    lock = visuals.get("lockPaintsToIndex")
    livery = visuals.get("HasOwnLivery")
    return CarVisualIndexSpace(
        model_key=model_key,
        valid=valid,
        defaults=defaults,
        unlock_groups=groups,
        gacha=gacha,
        lock_paints_to_index=lock if isinstance(lock, int) and not isinstance(lock, bool) else None,
        has_own_livery=bool(livery) if livery is not None else None,
        gacha_config_count=(len(configs) if isinstance(configs, Sequence)
                            and not isinstance(configs, (str, bytes)) else None),
        database_version=database_version,
        asset_version=asset_version,
    )


def _number_zone_count(environment: Any) -> Optional[int]:
    """How many racing-number anchors the bundle exposes, if it carries them.

    ``CarVisuals.GetNumberZonesCount`` returns the length of the car's
    ``RacingNumberGO`` collection, and the bundles name those anchors
    ``RacingNumber1``, ``RacingNumber2``, ``RacingNumber3``. Not every car ships
    them in its cosmetics bundle, so ``None`` means unknown, not zero.
    """
    seen = set()
    for obj in environment.objects:
        if obj.type.name != "GameObject":
            continue
        try:
            name = getattr(obj.read(), "m_Name", None)
        except Exception:
            continue
        if (isinstance(name, str) and name.startswith(NUMBER_ZONE_ANCHOR)
                and name[len(NUMBER_ZONE_ANCHOR):].isdigit()):
            seen.add(name)
    return len(seen) or None


def _trees(blob: bytes) -> Tuple[Optional[Mapping[str, Any]], Optional[Mapping[str, Any]]]:
    try:
        import UnityPy
    except ImportError as exc:  # pragma: no cover - optional extra
        raise CarVisualsError(
            "decoding a _common bundle needs UnityPy; install csr2-cdn[images]") from exc
    if not isinstance(blob, (bytes, bytearray)) or not blob:
        raise CarVisualsError("a non-empty asset bundle is required")
    if len(blob) > _MAX_BUNDLE_BYTES:
        raise CarVisualsError("asset bundle is implausibly large")
    try:
        environment = UnityPy.load(bytes(blob))
    except Exception:
        environment = UnityPy.load(io.BytesIO(bytes(blob)))
    visuals = unlockables = None
    zones = _number_zone_count(environment)
    for obj in environment.objects:
        if obj.type.name != "MonoBehaviour":
            continue
        try:
            tree = obj.read_typetree()
        except Exception:
            continue
        if not isinstance(tree, Mapping):
            continue
        if visuals is None and _VISUALS_MARKER in tree:
            visuals = tree
        if unlockables is None and _UNLOCKABLES_MARKER in tree:
            unlockables = tree
        if visuals is not None and unlockables is not None:
            break
    return visuals, unlockables, zones


def decode_common_bundle(blob: bytes, model_key: str, *,
                         database_version: Optional[str] = None,
                         asset_version: Optional[str] = None) -> CarVisualIndexSpace:
    """Decode one ``<crdb>_common`` bundle into its cosmetic index space."""
    visuals, unlockables, zones = _trees(blob)
    if visuals is None:
        raise CarVisualsError("no CarVisualsData behaviour in bundle for %r" % model_key)
    space = compose_index_space(model_key, visuals, unlockables,
                                database_version=database_version,
                                asset_version=asset_version)
    return space if zones is None else replace(space, number_zone_count=zones)


def strip_wheel_prefix(wheel_name: Any, model_key: Optional[str]) -> Any:
    """Drop the ``{model_key}_`` prefix the roster puts on wheel bundle names.

    The roster sends ``Ford_Mustang302_1970_Wheel1A_3D``; the bundle stores
    ``Wheel1A_3D``. A value that is not prefixed is returned unchanged.
    """
    if not isinstance(wheel_name, str) or not isinstance(model_key, str) or not model_key:
        return wheel_name
    prefix = model_key + "_"
    return wheel_name[len(prefix):] if wheel_name.startswith(prefix) else wheel_name


def common_asset_code(model_key: str) -> str:
    """The usual asset-database code for a model's cosmetics, ``X_common``."""
    if not isinstance(model_key, str) or not model_key:
        raise CarVisualsError("a model key is required")
    return model_key if model_key.lower().endswith("_common") else model_key + "_common"


def common_asset_candidates(model_key: str) -> Tuple[str, ...]:
    """Asset codes that may hold a model's cosmetics, best first.

    Most cars ship ``<model>_common``, but the Classic and LPClassic restoration
    models carry theirs in a bundle named after the model alone, which is why
    eleven live roster rows previously resolved to no index space at all.
    """
    code = common_asset_code(model_key)
    bare = code[: -len("_common")] if code.lower().endswith("_common") else code
    return (code, bare) if bare != code else (code,)


def load_index_space(cdn: Any, model_key: str) -> CarVisualIndexSpace:
    """Download and decode a model's cosmetics bundle through a ``CDN``."""
    tried, problems = [], []
    for code in common_asset_candidates(model_key):
        asset = cdn.database.assets.get(code)
        if asset is None:
            tried.append(code)
            continue
        try:
            return decode_common_bundle(cdn.download_asset(asset), code,
                                        database_version=str(cdn.database.version),
                                        asset_version=str(asset.version))
        except CarVisualsError as exc:
            problems.append("%s (%s)" % (code, exc))
    detail = "; ".join(problems) if problems else "no candidate asset: %s" % ", ".join(tried)
    raise CarVisualsError("no cosmetics bundle for %r: %s" % (model_key, detail))


def resolve_appearance(appearance: Any, space: Optional[CarVisualIndexSpace], library: Any,
                       *, model_key: Optional[str] = None) -> dict:
    """Resolve one roster appearance, reading each slot the way it is encoded.

    Returns a per-slot record with the wire value, the global ID it denotes, the
    library label, whether the car is eligible for it, and a status explaining
    any failure. ``paint`` is resolved through the car's list; every other
    numeric slot is a global ID that the list can only validate. Nothing is
    guessed: a paint without an index space is reported as such, because the
    global-ID reading of an index is wrong rather than merely unknown.
    """
    from csr2cdn.customization_evidence import SLOT_FIELDS

    out = {}
    for slot, wire_field in SLOT_FIELDS.items():
        code = getattr(appearance, wire_field, None) if appearance is not None else None
        if code is None:
            continue
        record = {"wire_value": code, "global_id": None, "name": None,
                  "indexed": slot in INDEX_SLOTS, "eligible": None,
                  "status": "unresolved"}

        if slot in NAME_SLOTS:
            # The wire value is the rim bundle's own asset code,
            # ``{model_key}_{BundleName}``, so it is already a CDN reference.
            bundle = strip_wheel_prefix(code, model_key)
            record["global_id"] = bundle
            record["asset_code"] = code if code != bundle else None
            match = match_library(library, model_key, slot, code)
            record["name"] = match.name if match is not None else bundle
            if space is None:
                record["status"] = "resolved_name_car_unknown"
            elif space.contains(slot, bundle):
                record["eligible"] = True
                record["status"] = "resolved_name"
            else:
                # Classic and restoration models list only part of their rims in
                # the cosmetics bundle while the asset itself exists, so an
                # absent name is not evidence the wheel is wrong.
                record["eligible"] = None
                record["status"] = "name_not_in_bundle_list"
            out[slot] = record
            continue

        # Tuner Stars values are global in every slot, paint included.
        is_tnr = isinstance(code, int) and not isinstance(code, bool) and code >= TNR_ID_FLOOR
        if slot in INDEX_SLOTS and not is_tnr:
            if space is None:
                record["status"] = "no_index_space"
                out[slot] = record
                continue
            target = space.resolve_index(slot, code)
            if target is None:
                record["status"] = "index_out_of_range"
                record["list_length"] = space.length(slot)
                out[slot] = record
                continue
            record["global_id"] = target
            record["eligible"] = True
            match = match_library(library, model_key, slot, target)
            if match is not None:
                record["name"] = match.name
                record["names"] = list(match.names)
                record["status"] = "resolved_via_index"
            else:
                record["status"] = "index_resolved_but_id_not_in_library"
            out[slot] = record
            continue

        if code in UNSET_VALUES:
            record["status"] = "unset"
            out[slot] = record
            continue

        if slot in PLACEMENT_SLOTS:
            # One of the car's RacingNumber mesh anchors, or 0 for hidden.
            record["global_id"] = code
            if type(code) is not int or code < 0:
                record["visible"] = None
                record["status"] = "invalid_placement"
            elif code == 0:
                record["visible"] = False
                record["name"] = "hidden"
                record["status"] = "resolved_placement"
            else:
                total = space.number_zone_count if space is not None else None
                record["visible"] = True
                record["anchor"] = "%s%d" % (NUMBER_ZONE_ANCHOR, code)
                record["name"] = record["anchor"]
                record["zone_count"] = total
                record["status"] = ("placement_out_of_range"
                                    if total is not None and code > total
                                    else "resolved_placement")
            out[slot] = record
            continue

        if slot in ZERO_MEANS_NONE and code == 0:
            record["status"] = "none_applied"
            out[slot] = record
            continue

        # Global library ID. A per-car list, where one exists, says only
        # whether this car is allowed to wear it.
        record["global_id"] = code
        if is_tnr:
            record["tuner_stars"] = True
        if space is not None and slot in ELIGIBILITY_SLOTS:
            record["eligible"] = space.contains(slot, code)
        match = match_library(library, model_key, slot, code)
        if match is not None:
            record["name"] = match.name
            record["names"] = list(match.names)
            record["status"] = "resolved_global_id"
        else:
            record["status"] = "global_id_not_in_library"
        out[slot] = record
    return out


__all__ = [
    "CAR_LIST_SLOTS",
    "ELIGIBILITY_SLOTS",
    "INDEXED_SLOTS",
    "INDEX_SLOTS",
    "LIBRARY_SLOT_ALIASES",
    "GACHA_SLOT_KEYS",
    "INT32_MAX",
    "INT32_MIN",
    "FLAG_SLOTS",
    "NUMBER_ZONE_ANCHOR",
    "NUMBER_ZONE_ANCHORS_PER_CAR",
    "PLACEMENT_SLOTS",
    "TNR_ID_FLOOR",
    "UNSET_VALUES",
    "ZERO_MEANS_NONE",
    "NAME_SLOTS",
    "SENTINEL",
    "WHEEL_SENTINEL",
    "CarVisualIndexSpace",
    "CarVisualsError",
    "common_asset_candidates",
    "common_asset_code",
    "compose_index_space",
    "compose_valid_ids",
    "gacha_values",
    "decode_common_bundle",
    "library_slots",
    "load_index_space",
    "match_library",
    "resolve_appearance",
    "split_groups",
    "strip_wheel_prefix",
]
