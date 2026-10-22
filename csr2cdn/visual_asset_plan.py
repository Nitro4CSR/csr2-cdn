"""Offline, database-derived Android ASTC visual library download plan.

The plan uses the real ``asset_database`` rows, **not** guessed versions or
remote lookups. All listed original ASTC library schemas have now been decoded
offline, but source IDs must not be treated as roster joins without evidence. The plan
never issues HTTP requests or loads user account data.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Optional, Sequence

from .cdn import CDN, DEFAULT_BASE_URL
from .database import AssetDatabase

# Slot -> exact asset code, state, join evidence. CarTunerStarsRimLibrary is
# specifically for *Tuner Stars*; it is not a universal wheel-name library.
# 'decode_supported' means a source-confirmed offline UnityFS schema; it
# does not assert that every source ID has a proven roster join.
_SOURCES: tuple[tuple[str, str, str, str], ...] = (
    ('paint', 'CarPaintLibrary', 'decode_supported', 'observed_numeric_id'),
    ('livery', 'CarLiveryLibrary', 'decode_supported', 'observed_numeric_id'),
    ('interior', 'CarInteriorLibrary', 'decode_supported', 'observed_numeric_id'),
    ('calliper', 'CarCalliperLibrary', 'decode_supported', 'observed_numeric_id'),
    ('color', 'CarColorLibrary', 'decode_supported', 'unverified_roster_join'),
    ('tuner_rim', 'CarTunerStarsRimLibrary', 'decode_supported', 'unverified_roster_join'),
    ('flag', 'CarFlagLibrary', 'decode_supported', 'observed_numeric_id'),
    ('racing_number', 'CarRacingNumberLibrary', 'decode_supported', 'observed_numeric_id'),
    ('license_plate', 'CarLicensePlateLibrary', 'decode_supported', 'observed_numeric_id'),
    ('wrap', 'CarWrapLibrary', 'decode_supported', 'unverified_roster_join'),
    ('livery_set', 'CarLiverySetLibrary', 'decode_supported', 'unverified_roster_join'),
    ('livery_zones', 'LiveryZonesSetLibrary', 'decode_supported', 'observed_numeric_id'),
)
VISUAL_ASSET_SLOTS: tuple[str, ...] = tuple(s[0] for s in _SOURCES)
# Historical default download group: seven additionally discovered assets.
# Some are now decoder-supported, but their live roster/UI semantics remain
# candidates. Preserve the existing default planner behavior.
PENDING_VISUAL_ASSET_SLOTS: tuple[str, ...] = (
    'tuner_rim', 'flag', 'racing_number', 'license_plate',
    'wrap', 'livery_set', 'livery_zones',
)
_SAFE_CODE = re.compile(r'^[A-Za-z][A-Za-z0-9_]{0,95}$')
_SAFE_VERSION = re.compile(r'^[0-9]{1,12}$')


@dataclass(frozen=True)
class VisualAssetCandidate:
    """One versioned asset present in a particular offline asset database."""

    slot: str
    code: str
    version: str
    platform: str
    quality: str
    size_bytes: int
    url: str
    decoder_status: str
    roster_join_status: str

    @property
    def filename(self) -> str:
        return f'{self.code}.{self.quality}.{self.version}'

    @property
    def native_schema_decoded(self) -> bool:
        """The source decoder is supported; not evidence of a roster join."""
        return self.decoder_status == 'decode_supported'

    @property
    def roster_id_match_candidate(self) -> bool:
        """The roster exposes an analogous numeric ID, not verified semantics."""
        return self.native_schema_decoded and self.roster_join_status == 'observed_numeric_id'

    @property
    def name_mapping_verified(self) -> bool:
        """Verified mapping ONLY, never merely decoder availability.

        This legacy property previously conflated source decoding with field
        correspondence.  No current built-in library has a proven semantic
        roster namespace; callers must use ``native_schema_decoded`` for
        source-parser availability and ``roster_id_match_candidate`` for
        provisional numeric correspondence instead.
        """
        return self.native_schema_decoded and self.roster_join_status == 'verified_roster_join'


@dataclass(frozen=True)
class VisualAssetPlan:
    """Versioned offline asset plan; absent assets reported, not fabricated."""

    database_version: str
    product_version: str
    branch_name: str
    platform: str
    quality: str
    candidates: tuple[VisualAssetCandidate, ...]
    absent_slots: tuple[str, ...] = ()

    @property
    def total_bytes(self) -> int:
        return sum(asset.size_bytes for asset in self.candidates)

    @property
    def urls(self) -> list[str]:
        return [asset.url for asset in self.candidates]

    def for_slot(self, slot: str) -> Optional[VisualAssetCandidate]:
        return next((asset for asset in self.candidates if asset.slot == slot), None)


def plan_visual_assets(database: AssetDatabase, *, slots: Optional[Sequence[str]] = None,
                       platform: str = 'ANDROID', quality: str = 'ASTC',
                       base_url: str = DEFAULT_BASE_URL) -> VisualAssetPlan:
    """Construct URLs from exact offline asset database entries.

    Android ASTC is the default. Alternative High quality is explicitly opt-in,
    and platform-specific asset equivalence is *not* asserted. Never fetches.
    Invalid or missing database entries cannot produce plausible-looking URLs.
    """
    if not isinstance(database, AssetDatabase):
        raise ValueError('an AssetDatabase is required')
    if platform != 'ANDROID' or quality not in ('ASTC', 'High'):
        raise ValueError('supported offline planning is ANDROID/ASTC or ANDROID/High only')
    if not isinstance(base_url, str) or not re.fullmatch(r'https://[A-Za-z0-9.-]+(?::[0-9]{1,5})?', base_url):
        raise ValueError('base URL must be a simple HTTPS origin')
    if slots is None:
        selected = PENDING_VISUAL_ASSET_SLOTS
    else:
        if isinstance(slots, (str, bytes)):
            raise ValueError('slots must be an iterable of known slot names')
        selected = tuple(slots)
        if len(selected) > len(_SOURCES) or any(type(s) is not str or s not in VISUAL_ASSET_SLOTS for s in selected):
            raise ValueError('unknown visual asset slot')
        if len(set(selected)) != len(selected):
            raise ValueError('duplicate visual asset slot')
    client = CDN(base_url=base_url, platform=platform, quality=quality)
    pending = []
    absent = []
    sources = {s[0]: s for s in _SOURCES}
    for slot in selected:
        _, code, status, join = sources[slot]
        asset = database.assets.get(code)
        if asset is None:
            absent.append(slot)
            continue
        version = str(asset.version)
        if not _SAFE_CODE.fullmatch(str(asset.code)) or not _SAFE_VERSION.fullmatch(version):
            raise ValueError('unsafe library asset code or version in database')
        size = asset.size(quality)
        if size <= 0 or size > 50 * 1024 * 1024:
            absent.append(slot)
            continue
        pending.append(VisualAssetCandidate(
            slot, asset.code, version, platform, quality, size,
            client.asset_url(asset.code, version, platform=platform, quality=quality),
            status, join))
    def _header(name: str) -> str:
        value = database.header.get(name)
        value = str(value) if value is not None else ''
        return value if len(value) <= 128 and all(c.isalnum() or c in '_-.' for c in value) else ''
    return VisualAssetPlan(_header('version'), _header('product_version'),
                           _header('branch_name'), platform, quality, tuple(pending), tuple(absent))


def plan_visual_assets_from_file(path: str | Path, *, slots: Optional[Sequence[str]] = None,
                                 platform: str = 'ANDROID', quality: str = 'ASTC') -> VisualAssetPlan:
    """Load an existing asset database file locally, with a bounded JSON read."""
    target = Path(path)
    if not target.is_file() or not 128 <= target.stat().st_size <= 32 * 1024 * 1024:
        raise ValueError('asset database missing or unexpectedly sized')
    try:
        db = AssetDatabase.loads(target.read_bytes())
        return plan_visual_assets(db, slots=slots, platform=platform, quality=quality)
    except (UnicodeError, json.JSONDecodeError, TypeError, KeyError, AttributeError) as e:
        raise ValueError('invalid local asset database') from None
