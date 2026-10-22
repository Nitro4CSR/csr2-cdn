"""Decode a cosmetic library from its Unity type tree.

``visual_library_bundle`` parses these libraries straight out of the serialized
bytes, which is fast and dependency-free but has to know each container's exact
shape. Four Tuner Stars libraries are not in its repertoire and fail closed:
``CarTunerStarsLiveryLibrary``, ``CarTunerStarsLiverySetLibrary``,
``CarTunerStarsTireLibrary`` and ``CarTunerStarsBoostColorLibrary``. A live
roster row then has no label source at all -- a Supra reporting livery
``1000029`` resolved to nothing for exactly this reason.

Every one of those libraries *is* readable through UnityPy's type tree, so this
module decodes them generically: find the record list, take each entry's ``ID``
and whichever name field it carries. It is a fallback, not a replacement; the
binary decoder stays the primary path where it works.

Needs UnityPy (``pip install csr2-cdn[images]``).
"""
from __future__ import annotations

import io
from typing import Any, Iterable, Mapping, Optional, Sequence, Tuple

from csr2cdn.errors import Csr2CdnError
from csr2cdn.game_labels import GameVisualLibrary, VisualCodeName

#: Library asset name -> the slot its records belong to.
LIBRARY_SLOTS: Mapping[str, str] = {
    "CarPaintLibrary": "paint",
    "CarTunerStarsPaintLibrary": "paint",
    "CarInteriorLibrary": "interior",
    "CarTunerStarsInteriorLibrary": "interior",
    "CarCalliperLibrary": "calliper",
    "CarTunerStarsCalliperLibrary": "calliper",
    "CarLiveryLibrary": "livery",
    "CarTunerStarsLiveryLibrary": "livery",
    "CarLiverySetLibrary": "livery_set",
    "CarTunerStarsLiverySetLibrary": "livery_set",
    # Distinct from the two above despite the name: 13 shader zone masks
    # (FULL BODY, CONTRAST, ACCENT and inverted variants), which is what the
    # roster's car_liveryZonesSet_id actually selects.
    "LiveryZonesSetLibrary": "livery_zone_mask",
    "TunerStarsLiveryZonesSetLibrary": "livery_zone_mask",
    "CarFlagLibrary": "decal_flag",
    "CarRacingNumberLibrary": "decal_number",
    "CarLicensePlateLibrary": "decal_numberplate_style",
    "CarColorLibrary": "color",
    "CarWrapLibrary": "wrap",
    "CarTunerStarsRimLibrary": "tuner_rim",
    "CarTunerStarsTireLibrary": "tire",
    "CarTunerStarsBoostColorLibrary": "boost_color",
}

#: Name fields seen across the libraries, in order of preference.
NAME_FIELDS: Tuple[str, ...] = ("Name", "NameID", "DisplayName", "Zone1Name", "Code")
#: Zone-style libraries expose two names; both are kept.
ZONE_FIELDS: Tuple[str, ...] = ("Zone1Name", "Zone2Name")

_MAX_BYTES = 32 * 1024 * 1024
_MAX_RECORDS = 20000


class VisualTypetreeError(Csr2CdnError):
    """A library asset could not be decoded through its type tree."""


def _entries(tree: Mapping[str, Any]) -> Optional[Sequence[Mapping[str, Any]]]:
    """The record list: the longest list of objects carrying an ``ID``."""
    best = None
    for key, value in tree.items():
        if key.startswith("m_") or not isinstance(value, list) or not value:
            continue
        if not isinstance(value[0], Mapping) or "ID" not in value[0]:
            continue
        if best is None or len(value) > len(best):
            best = value
    return best


def _label(entry: Mapping[str, Any]) -> Tuple[Optional[str], Tuple[str, ...]]:
    zones = tuple(str(entry[f]) for f in ZONE_FIELDS
                  if isinstance(entry.get(f), str) and entry[f])
    for field in NAME_FIELDS:
        value = entry.get(field)
        if isinstance(value, str) and value:
            return value, zones
    return None, zones


def decode_library_typetree(blob: bytes, library: str, *,
                            source_sha256: Optional[str] = None) -> GameVisualLibrary:
    """Decode one cosmetic library asset into labelled records."""
    slot = LIBRARY_SLOTS.get(library)
    if slot is None:
        raise VisualTypetreeError("unknown cosmetic library %r" % library)
    if not isinstance(blob, (bytes, bytearray)) or not blob:
        raise VisualTypetreeError("a non-empty library asset is required")
    if len(blob) > _MAX_BYTES:
        raise VisualTypetreeError("library asset is implausibly large")
    try:
        import UnityPy
    except ImportError as exc:  # pragma: no cover - optional extra
        raise VisualTypetreeError(
            "type-tree decoding needs UnityPy; install csr2-cdn[images]") from exc
    try:
        environment = UnityPy.load(bytes(blob))
    except Exception:
        environment = UnityPy.load(io.BytesIO(bytes(blob)))

    records = []
    seen = set()
    for obj in environment.objects:
        if obj.type.name != "MonoBehaviour":
            continue
        try:
            tree = obj.read_typetree()
        except Exception:
            continue
        if not isinstance(tree, Mapping):
            continue
        entries = _entries(tree)
        if not entries:
            continue
        if len(entries) > _MAX_RECORDS:
            raise VisualTypetreeError("library record list is implausibly long")
        for entry in entries:
            code = entry.get("ID")
            if type(code) is not int or code in seen:
                continue
            name, zones = _label(entry)
            if name is None:
                continue
            seen.add(code)
            records.append(VisualCodeName(
                model_key="*", slot=slot, code=code, name=name,
                source_library=library, source_sha256=source_sha256,
                names=zones or (name,)))
    if not records:
        raise VisualTypetreeError("no labelled records in %r" % library)
    return GameVisualLibrary(records=tuple(records))


def decode_library(blob: bytes, library: str, *,
                   source_sha256: Optional[str] = None) -> GameVisualLibrary:
    """Decode a library, preferring the binary parser and falling back here."""
    try:
        from csr2cdn.visual_library_bundle import decode_visual_unityfs
        return decode_visual_unityfs(blob, library=library)
    except Exception:
        return decode_library_typetree(blob, library, source_sha256=source_sha256)


def merge(libraries: Iterable[GameVisualLibrary]) -> GameVisualLibrary:
    """Combine decoded libraries, keeping the first label for each code."""
    records, seen = [], set()
    for library in libraries:
        for record in library.records:
            key = (record.model_key, record.slot, record.code)
            if key in seen:
                continue
            seen.add(key)
            records.append(record)
    return GameVisualLibrary(records=tuple(records))


__all__ = [
    "LIBRARY_SLOTS",
    "NAME_FIELDS",
    "ZONE_FIELDS",
    "VisualTypetreeError",
    "decode_library",
    "decode_library_typetree",
    "merge",
]
