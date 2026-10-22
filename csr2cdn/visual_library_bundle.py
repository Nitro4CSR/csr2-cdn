"""Read-only decoder for observed CSR2 Android ASTC visual asset libraries.

Grounded in the uploaded CarPaintLibrary.ASTC.1195, CarLiveryLibrary.ASTC.1042
CarInteriorLibrary.ASTC.1139, CarCalliperLibrary.ASTC.1004 and
CarColorLibrary.ASTC.594 and seven additional observed ASTC bundles. Global IDs come
from each library's explicit ``ID`` field; no model-specific naming guesses.

The original game bundles are never included in the Python distribution.
Unrecognized layouts fail closed; there is no CDN or gameplay I/O.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from pathlib import Path
import struct
from typing import Iterable

from .game_labels import GameVisualLibrary, VisualCodeName
from .service_prestige_unityfs import load_unityfs

_MAX_FILE = 8 * 1024 * 1024
_MAX_ITEMS = 10000
_MAX_LABEL = 180
_SPECS = {
    'CarPaintLibrary': ('paint', ('CarPaints', 'UnlockLevel', 'CarPaintType', 'DiffuseTint')),
    'CarLiveryLibrary': ('livery', ('CarLiveries', 'NameID', 'AlbedoTexture', 'CarLiveryType')),
    'CarInteriorLibrary': ('interior', ('CarInteriors', 'Zone1Name', 'Zone2Name', 'InteriorTilingZone2')),
    'CarCalliperLibrary': ('calliper', ('CarCallipers', 'Name', 'Zone1DiffuseTint', 'CashPrice')),
    'CarColorLibrary': ('color', ('CarColors', 'NameID', 'color', 'isModified')),
    'CarFlagLibrary': ('decal_flag', ('CarFlags', 'NameID', 'CountryName', 'AlbedoTexture')),
    'CarRacingNumberLibrary': ('decal_number', ('CarRacingNumbers', 'CarNumberType', 'AlbedoTexture')),
    'CarLicensePlateLibrary': ('decal_numberplate_style', ('CarLicensePlates', 'LicensePlateType', 'Category')),
    'CarWrapLibrary': ('wrap', ('CarWraps', 'ForceCarWrapDiffuseTint', 'CarPaintType')),
    'CarLiverySetLibrary': ('livery_set', ('CarLiverySets', 'isNoLivery', 'liveryZoneID', 'SwatchTexture')),
    'LiveryZonesSetLibrary': ('livery_zones_set', ('CarLiveryZoneSets', 'LocalisationStringID', 'PickFromBlueID', 'Zones')),
    'CarTunerStarsRimLibrary': ('tuner_rim', ('CarRims', 'AvailableSizes', 'CompatibleCars', 'DefaultRim')),
    'CarTunerStarsPaintLibrary': ('paint', ('CarTNRPaints', 'TNRCarPaint', 'Category', 'IncludeToCar')),
    'CarTunerStarsInteriorLibrary': ('interior', ('CarTNRInteriors', 'TNRCarInterior', 'Category', 'IncludeToCar')),
    'CarTunerStarsCalliperLibrary': ('calliper', ('CarTNRCallipers', 'TNRCarCalliper', 'Category', 'IncludeToCar')),
}



_TNR_LIBRARY_NAMES = frozenset(('CarTunerStarsPaintLibrary', 'CarTunerStarsInteriorLibrary', 'CarTunerStarsCalliperLibrary'))


class VisualLibrarySourceError(ValueError):
    """Malformed, unsupported or ambiguous game visual library."""


def _u32(blob: bytes, pos: int) -> int:
    if pos < 0 or pos + 4 > len(blob):
        raise VisualLibrarySourceError('record is truncated')
    return struct.unpack_from('<I', blob, pos)[0]


def _i32(blob: bytes, pos: int) -> int:
    if pos < 0 or pos + 4 > len(blob):
        raise VisualLibrarySourceError('record is truncated')
    return struct.unpack_from('<i', blob, pos)[0]


def _unity_string(blob: bytes, pos: int, *, empty: bool = False) -> tuple[str, int]:
    length = _u32(blob, pos)
    if length > 4096 or pos + 4 + length > len(blob):
        raise VisualLibrarySourceError('invalid Unity string length')
    try:
        label = blob[pos + 4:pos + 4 + length].decode('utf-8')
    except UnicodeError:
        raise VisualLibrarySourceError('invalid UTF-8 in visual record') from None
    if not label and not empty:
        raise VisualLibrarySourceError('invalid visual label')
    return label, (pos + 4 + length + 3) & ~3


def _string_array(node: bytes, pos: int, *, limit: int = 1000) -> tuple[list[str], int]:
    count = _u32(node, pos)
    if count > limit:
        raise VisualLibrarySourceError('visual string array exceeds limit')
    values = []
    pos += 4
    for _ in range(count):
        text, pos = _unity_string(node, pos, empty=True)
        values.append(text)
    return values, pos


def _rim_trailer(node: bytes, pos: int) -> bool:
    # The real Tuner Stars asset has two *root-level* string arrays after
    # the 480 CarRim rows (CarNames, DefaultRim), not arrays per rim.
    try:
        names, pos = _string_array(node, pos, limit=1000)
        defaults, pos = _string_array(node, pos, limit=1000)
    except VisualLibrarySourceError:
        return False
    return (bool(names) and bool(defaults) and
            0 <= len(node) - pos <= 128)


def _parse_records(node: bytes, pos: int, count: int, kind: str) -> tuple[list[tuple[int, str, tuple[str, ...]]], int]:
    records = []
    seen = set()
    for _ in range(count):
        if kind in ('paint', 'wrap'):
            name, pos = _unity_string(node, pos)
            _unlock, ident, _paint_type = _i32(node, pos), _i32(node, pos + 4), _i32(node, pos + 8)
            pos += 12 + (14 * 4)  # two RGBA tints, six float shader attributes
            names = (name,)
        elif kind == 'livery':
            ident = _i32(node, pos)
            name, pos = _unity_string(node, pos + 4)
            _typ = _i32(node, pos)
            pos += 4
            for _ in range(4):
                _, pos = _unity_string(node, pos, empty=True)
            _tile, _cash = _i32(node, pos), _i32(node, pos + 4)
            pos = (pos + 8 + 1 + 3) & ~3  # OEM bool, Unity alignment
            pos += 8  # F0 and Shininess
            names = (name,)
        elif kind == 'interior':
            ident = _i32(node, pos)
            zone1, pos = _unity_string(node, pos + 4)
            zone2, pos = _unity_string(node, pos)
            pos += 2 * 16  # two RGBA tints
            pos = (pos + 1 + 3) & ~3  # InteriorTilingZone2 bool
            _origin, _cash = _i32(node, pos), _i32(node, pos + 4)
            pos += 8
            names = (zone1, zone2)
        elif kind == 'decal_flag':
            ident = _i32(node, pos)
            _code, pos = _unity_string(node, pos + 4)
            country, pos = _unity_string(node, pos)
            for _ in range(2):
                _, pos = _unity_string(node, pos, empty=True)
            pos += 4                         # TileFactor
            pos = (pos + 1 + 3) & ~3         # OEM bool
            pos += 8                         # F0, Shininess
            names = (country,)
        elif kind == 'decal_number':
            ident = _i32(node, pos)
            name, pos = _unity_string(node, pos + 4)
            pos += 4                         # CarNumberType
            _, pos = _unity_string(node, pos, empty=True)
            names = (name,)
        elif kind == 'decal_numberplate_style':
            ident = _i32(node, pos)
            name, pos = _unity_string(node, pos + 4)
            for _ in range(3):               # Type, category, texture
                _, pos = _unity_string(node, pos, empty=True)
            names = (name,)
        elif kind == 'livery_set':
            ident = _i32(node, pos)
            pos = (pos + 5 + 3) & ~3         # ID + aligned isNoLivery bool
            name, pos = _unity_string(node, pos)
            pos += 8                        # liveryID, liveryZoneID
            _, pos = _unity_string(node, pos, empty=True)
            names = (name,)
        elif kind == 'livery_zones_set':
            ident = _i32(node, pos)
            name, pos = _unity_string(node, pos + 4)
            _, pos = _unity_string(node, pos, empty=True)  # localisation key
            pos = (pos + 1 + 3) & ~3         # PickFromBlueID bool
            count_zones = _u32(node, pos)
            if count_zones > 64 or pos + 4 + count_zones > len(node):
                raise VisualLibrarySourceError('invalid livery zone flags')
            pos = (pos + 4 + count_zones + 3) & ~3
            names = (name,)
        elif kind == 'tuner_rim':
            ident = _i32(node, pos)
            name, pos = _unity_string(node, pos + 4)
            count_sizes = _u32(node, pos)
            if count_sizes > 64 or pos + 4 + count_sizes * 4 > len(node):
                raise VisualLibrarySourceError('invalid rim sizes')
            pos += 4 + count_sizes * 4
            _, pos = _unity_string(node, pos, empty=True)  # BrandName
            _, pos = _unity_string(node, pos, empty=True)  # Category
            _, pos = _string_array(node, pos, limit=1000)  # CompatibleCars
            names = (name,)
        elif kind in ('calliper', 'color'):
            ident = _i32(node, pos)
            name, pos = _unity_string(node, pos + 4, empty=kind == 'color')
            pos += 16  # one RGBA tint, four 32-bit floats
            if kind == 'calliper':
                _origin, _cash = _i32(node, pos), _i32(node, pos + 4)
                pos += 8
            # Real CarColorLibrary has an intentionally empty NameID for ID 9.
            # Retain its source position/ID for validation; omit it from named exports.
            names = (name,) if name else ()
        else:
            raise VisualLibrarySourceError('unsupported visual record kind')
        if (not (-2**31 <= ident < 2**31) or
                (ident < 0 and kind != 'wrap') or ident in seen or pos > len(node)):
            raise VisualLibrarySourceError('invalid or duplicated visual ID')
        names = tuple(re.sub(r'\s+', ' ', s).strip() for s in names)
        if any(not s or len(s) > _MAX_LABEL or any(ord(c) < 32 for c in s) for s in names):
            raise VisualLibrarySourceError('invalid visual record name')
        if not names and kind != 'color':
            raise VisualLibrarySourceError('missing visual record name')
        seen.add(ident)
        records.append((ident, names[0] if names else '', names))
    return records, pos


def _parse_tnr_records(node: bytes, pos: int, count: int, slot: str):
    """Read the observed TNR MonoBehaviour primary array, not its extra tables.

    The actual TNR structs append an IncludeToCar integer and a Category
    string to the otherwise familiar visual record fields. Their categories
    are either All or an exact car model identifier. We do not infer missing
    model-specific eligibility rules from the remaining trailer arrays.
    """
    rows = []
    seen = set()
    for _ in range(count):
        if slot == 'paint':
            label, pos = _unity_string(node, pos)
            _unlock, ident, _type = _i32(node, pos), _i32(node, pos + 4), _i32(node, pos + 8)
            pos += 12 + 14 * 4
            names = (label,)
        elif slot == 'interior':
            ident = _i32(node, pos)
            zone1, pos = _unity_string(node, pos + 4)
            zone2, pos = _unity_string(node, pos)
            pos += 32                  # two RGBA tints
            pos = (pos + 1 + 3) & ~3    # bool
            pos += 8                   # origin, price
            names = (zone1, zone2)
        elif slot == 'calliper':
            ident = _i32(node, pos)
            label, pos = _unity_string(node, pos + 4)
            pos += 16 + 8              # RGBA, origin, price
            names = (label,)
        else:
            raise VisualLibrarySourceError('unsupported TNR slot')
        _include_to_car = _i32(node, pos)
        category, pos = _unity_string(node, pos + 4)
        category = category.strip()
        # Avoid promoting a malformed category to a wildcard for every car.
        if (not 1_000_000 <= ident < 2_000_000 or ident in seen or
                (category != 'All' and
                 (not re.fullmatch(r'[A-Za-z0-9_]{1,160}', category) or 'TNR' not in category))):
            raise VisualLibrarySourceError('invalid TNR ID or category')
        names = tuple(re.sub(r'\s+', ' ', name).strip() for name in names)
        if any(not x or len(x) > _MAX_LABEL or any(ord(c) < 32 for c in x) for x in names):
            raise VisualLibrarySourceError('invalid TNR visual name')
        seen.add(ident)
        rows.append((ident, names[0], names, '*' if category == 'All' else category))
    return rows, pos


def _extract_tnr(node: bytes, data_offset: int, slot: str):
    """Require one complete TNR primary array with distinct declared IDs."""
    valid = []
    for pos in range(data_offset + 48, min(data_offset + 2048, len(node) - 64), 4):
        count = _u32(node, pos)
        if not 20 <= count <= 2000:
            continue
        try:
            rows, end = _parse_tnr_records(node, pos + 4, count, slot)
        except (VisualLibrarySourceError, struct.error, UnicodeError):
            continue
        # Real TNR paint/interior files contain additional source tables after
        # their complete primary name arrays. Those tables are not decoded.
        if len(rows) == count and 0 <= len(node) - end <= 256 * 1024:
            valid.append(rows)
    if len(valid) != 1:
        raise VisualLibrarySourceError('unique complete TNR primary array not found')
    return valid[0]


def _extract(raw: bytes, library: str) -> list[tuple[int, str, tuple[str, ...]]]:
    if type(raw) is not bytes or not 64 <= len(raw) <= _MAX_FILE or library not in _SPECS:
        raise VisualLibrarySourceError('unsupported visual library asset')
    try:
        _, engine, version, nodes = load_unityfs(raw)
    except (ValueError, IndexError, struct.error) as error:
        raise VisualLibrarySourceError('invalid UnityFS library container') from None
    if version != 8 or engine != '2021.3.16f1' or len(nodes) != 1:
        raise VisualLibrarySourceError('unsupported visual library UnityFS layout')
    _, node = nodes[0]
    if len(node) < 512 or struct.unpack_from('>I', node, 8)[0] != 22:
        raise VisualLibrarySourceError('unsupported Unity serialization version')
    data_offset = struct.unpack_from('>Q', node, 32)[0]
    if not 48 <= data_offset <= len(node) - 256:
        raise VisualLibrarySourceError('unsupported Unity object bounds')
    slot, required = _SPECS[library]
    metadata = node[:data_offset]
    if not all(field.encode('ascii') + b'\x00' in metadata for field in required):
        raise VisualLibrarySourceError('expected library type-tree schema absent')
    if library.encode('ascii') not in (node[data_offset:] if library in _TNR_LIBRARY_NAMES
                                         else node[data_offset:data_offset + 512]):
        raise VisualLibrarySourceError('library asset identity absent')
    if library in _TNR_LIBRARY_NAMES:
        return _extract_tnr(node, data_offset, slot)
    # The observed MonoBehaviour contains a fixed header then a typed array.
    # Locate that array by validating the entire declared record set, not by
    # hardcoding the version-specific array address or searching for names.
    valid = []
    for pos in range(data_offset + 48, min(data_offset + 2048, len(node) - 32), 4):
        count = _u32(node, pos)
        minimum = {'color': 2, 'decal_numberplate_style': 2,
                   'livery_zones_set': 2, 'wrap': 20}.get(slot, 100)
        if not minimum <= count <= _MAX_ITEMS:
            continue
        try:
            rows, end = _parse_records(node, pos + 4, count, slot)
        except (VisualLibrarySourceError, struct.error, UnicodeError):
            continue
        # Calliper/colour assets have a slightly longer serialized trailer
        # than the previously observed paint, interior and livery assets.
        max_trailer = 512 if slot in ('calliper', 'color', 'livery_zones_set') else 256
        trailer_ok = (_rim_trailer(node, end) if slot == 'tuner_rim'
                      else 0 <= len(node) - end <= max_trailer)
        if trailer_ok and len(rows) == count:
            valid.append(rows)
    if len(valid) != 1:
        raise VisualLibrarySourceError('unique complete visual record array not found')
    return valid[0]


def decode_visual_unityfs(raw: bytes, *, library: str) -> GameVisualLibrary:
    """Produce global ID labels for one evidenced game visual library.

    IDs are shared across vehicle models; ``model_key='*'`` denotes a global
    library ID, while model-specific bindings take precedence when both exist.
    Interior ``name`` is zone one; ``names`` preserves both official zones.
    The colour library has 11 IDs but one intentionally unnamed entry: it is
    not exported as a fake label. Colour ID mappings are available through
    ``library.match(model_key, 'color', id)`` but are *not* automatically
    equated with roster decal colour fields without additional wire evidence.
    """
    rows = _extract(raw, library)
    sha = hashlib.sha256(raw).hexdigest()
    slot = _SPECS[library][0]
    if library in _TNR_LIBRARY_NAMES:
        return GameVisualLibrary(tuple(VisualCodeName(
            model_key=model, slot=slot, code=ident, name=name,
            source_library=library, source_sha256=sha, names=names,
        ) for ident, name, names, model in rows))
    return GameVisualLibrary(tuple(VisualCodeName(
        model_key='*', slot=slot, code=ident, name=name,
        source_library=library, source_sha256=sha, names=names,
    ) for ident, name, names in rows if name))


def load_visual_unityfs(path: str | Path, *, library: str | None = None) -> GameVisualLibrary:
    """Read one local original asset bundle without network access."""
    file = Path(path)
    label = library or file.name.split('.')[0]
    if not file.is_file() or not 64 <= file.stat().st_size <= _MAX_FILE:
        raise VisualLibrarySourceError('visual library bundle missing or oversized')
    return decode_visual_unityfs(file.read_bytes(), library=label)


def load_visual_libraries_unityfs(paths: Iterable[str | Path]) -> GameVisualLibrary:
    """Merge supported game visual libraries; reject ambiguous per-slot IDs."""
    records = []
    seen = set()
    for path in paths:
        for record in load_visual_unityfs(path).records:
            key = (record.slot, record.code)
            if key in seen:
                raise VisualLibrarySourceError('duplicate visual IDs across source libraries')
            seen.add(key)
            records.append(record)
    if not records:
        raise VisualLibrarySourceError('no source visual libraries supplied')
    return GameVisualLibrary(tuple(records))
