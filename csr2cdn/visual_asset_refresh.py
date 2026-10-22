"""Offline comparison of versioned Android visual assets and local bundle files.

Two *supplied* asset databases are required for freshness claims. This module
never discovers or downloads a newer database and never accesses game services.
Matching a filename and size is a local-file check, not proof that a library's
contents are authentic or that roster wheel/palette joins are correct.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Sequence
import argparse
import json
import re

from .visual_asset_plan import (VISUAL_ASSET_SLOTS, VisualAssetCandidate,
                                VisualAssetPlan, plan_visual_assets_from_file)


@dataclass(frozen=True)
class VisualAssetRefreshSlot:
    slot: str
    status: str
    before_version: Optional[str]
    after_version: Optional[str]
    before_size: Optional[int]
    after_size: Optional[int]
    local_status: str = 'not_checked'
    filename: Optional[str] = None
    url: Optional[str] = field(default=None, repr=False)

    @property
    def needs_review(self) -> bool:
        return self.status != 'unchanged' or self.local_status in ('missing', 'size_mismatch', 'unsafe_file')

    def as_dict(self, *, include_urls: bool = False) -> dict[str, Any]:
        out = dict(slot=self.slot, status=self.status,
                   before_version=self.before_version, after_version=self.after_version,
                   before_size=self.before_size, after_size=self.after_size,
                   local_status=self.local_status, filename=self.filename,
                   needs_review=self.needs_review)
        if include_urls and self.url is not None:
            out['url'] = self.url
        return out


@dataclass(frozen=True)
class VisualAssetRefreshReport:
    """Attribute-first report for comparisons of two existing asset databases."""
    before_database: str
    after_database: str
    quality: str
    slots: tuple[VisualAssetRefreshSlot, ...]

    def __getattr__(self, slot: str) -> VisualAssetRefreshSlot:
        for item in self.slots:
            if item.slot == slot:
                return item
        raise AttributeError(slot)

    @property
    def changed(self) -> int:
        return sum(s.status != 'unchanged' for s in self.slots)

    @property
    def local_missing(self) -> int:
        return sum(s.local_status == 'missing' for s in self.slots)

    def as_dict(self, *, include_urls: bool = False) -> dict[str, Any]:
        return {
            'status': 'offline_visual_asset_refresh_candidate_only',
            'mode': 'offline', 'network_requests': 0,
            'before_database_version': self.before_database,
            'after_database_version': self.after_database,
            'platform': 'ANDROID', 'quality': self.quality,
            'changed_slots': self.changed,
            'local_missing_slots': self.local_missing,
            'only_supplied_database_versions_checked': True,
            'local_size_match_does_not_verify_content': True,
            'wheel_and_color_roster_joins_verified': False,
            'slots': {slot.slot: slot.as_dict(include_urls=include_urls) for slot in self.slots},
        }


def _local_status(asset: Optional[VisualAssetCandidate], directory: Optional[Path]) -> str:
    if directory is None:
        return 'not_checked'
    if asset is None:
        return 'not_in_candidate_database'
    # The planner already enforces safe asset codes and numeric versions.
    target = directory / asset.filename
    if target.is_symlink():
        return 'unsafe_file'
    try:
        if not target.exists():
            return 'missing'
        if not target.is_file():
            return 'unsafe_file'
        if target.stat().st_size != asset.size_bytes:
            return 'size_mismatch'
    except OSError:
        return 'unsafe_file'
    return 'size_matches_unverified_content'


def compare_visual_asset_plans(before: VisualAssetPlan, after: VisualAssetPlan, *,
                               bundles_dir: Optional[str | Path] = None) -> VisualAssetRefreshReport:
    """Report exact version/size changes without downloading or decoding assets.

    Uses the public plan model to validate platform, quality, source IDs and
    filenames. A same-version size change is classified as anomalous rather
    than silently treated as an update.
    """
    if not isinstance(before, VisualAssetPlan) or not isinstance(after, VisualAssetPlan):
        raise TypeError('two typed asset plans required')
    if before.platform != 'ANDROID' or after.platform != 'ANDROID' or before.quality != after.quality:
        raise ValueError('incompatible platform or quality')
    if before.quality not in ('ASTC', 'High'):
        raise ValueError('unsupported quality')
    # Public plan objects may also be constructed by callers. Recheck filename-
    # bearing fields even when no on-disk database parser was involved.
    for plan in (before, after):
        for item in plan.candidates:
            if (not isinstance(item, VisualAssetCandidate) or
                type(item.slot) is not str or item.slot not in VISUAL_ASSET_SLOTS or
                type(item.code) is not str or
                not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,95}', item.code) or
                type(item.version) is not str or
                not re.fullmatch(r'[0-9]{1,12}', item.version) or
                type(item.platform) is not str or item.platform != 'ANDROID' or
                item.quality != plan.quality or
                type(item.size_bytes) is not int or not 0 < item.size_bytes <= 50 * 1024 * 1024 or
                type(item.url) is not str or not item.url.startswith('https://')):
                raise ValueError('invalid asset plan candidate')
    old = {x.slot: x for x in before.candidates}
    new = {x.slot: x for x in after.candidates}
    if len(old) != len(before.candidates) or len(new) != len(after.candidates):
        raise ValueError('duplicate asset slots')
    selected = set(old) | set(new) | set(before.absent_slots) | set(after.absent_slots)
    if any(s not in VISUAL_ASSET_SLOTS for s in selected):
        raise ValueError('unknown asset slot')
    directory = None
    if bundles_dir is not None:
        directory = Path(bundles_dir)
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError('bundle directory must exist and cannot be a symlink')
    result = []
    for slot in sorted(selected):
        left, right = old.get(slot), new.get(slot)
        if left is not None and right is not None and left.code != right.code:
            raise ValueError('source library code changed unexpectedly')
        if left is None and right is None:
            status = 'absent_both'
        elif left is None:
            status = 'introduced'
        elif right is None:
            status = 'removed'
        elif left.version != right.version:
            status = 'version_changed'
        elif left.size_bytes != right.size_bytes:
            status = 'same_version_size_changed'
        else:
            status = 'unchanged'
        result.append(VisualAssetRefreshSlot(
            slot=slot, status=status,
            before_version=left.version if left else None,
            after_version=right.version if right else None,
            before_size=left.size_bytes if left else None,
            after_size=right.size_bytes if right else None,
            local_status=_local_status(right, directory),
            filename=right.filename if right else None,
            url=right.url if right else None,
        ))
    return VisualAssetRefreshReport(before.database_version, after.database_version,
                                    before.quality, tuple(result))


def compare_visual_asset_databases(before_path: str | Path, after_path: str | Path, *,
                                   bundles_dir: Optional[str | Path] = None,
                                   slots: Optional[Sequence[str]] = None,
                                   quality: str = 'ASTC') -> VisualAssetRefreshReport:
    """Read only local asset databases. No HTTP is performed or implied."""
    selected = VISUAL_ASSET_SLOTS if slots is None else slots
    before = plan_visual_assets_from_file(before_path, slots=selected, quality=quality)
    after = plan_visual_assets_from_file(after_path, slots=selected, quality=quality)
    return compare_visual_asset_plans(before, after, bundles_dir=bundles_dir)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description='Offline visual asset version and local file audit')
    parser.add_argument('--before-database', help='previous local asset database')
    parser.add_argument('--after-database', help='comparison local asset database')
    parser.add_argument('--bundles-dir', help='directory of already downloaded ASTC files')
    parser.add_argument('--quality', choices=('ASTC', 'High'), default='ASTC')
    parser.add_argument('--slot', action='append', choices=VISUAL_ASSET_SLOTS)
    parser.add_argument('--show-urls', action='store_true', help='include exact candidate CDN URLs')
    args = parser.parse_args(argv)
    if args.before_database is None and args.after_database is None:
        print(json.dumps({'mode': 'dry_run', 'network_requests': 0,
                          'required': ['--before-database', '--after-database'],
                          'optional': ['--bundles-dir', '--slot', '--show-urls'],
                          'wheel_and_color_roster_joins_verified': False}))
        return 0
    if not args.before_database or not args.after_database:
        parser.error('both local asset databases are required')
    try:
        r = compare_visual_asset_databases(args.before_database, args.after_database,
                                         bundles_dir=args.bundles_dir, slots=args.slot,
                                         quality=args.quality)
    except (OSError, ValueError, TypeError):
        print(json.dumps({'status': 'invalid_offline_asset_source', 'network_requests': 0}))
        return 2
    print(json.dumps(r.as_dict(include_urls=args.show_urls), indent=2, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
