"""Dev39: test whether unmatched received *paint* IDs exist in CarColorLibrary.

The roster field is paint_id; CarColorLibrary is a separate color palette. A
numeric overlap is reported as evidence only, never treated as paint identity,
eligibility, a 'default' instruction, or a verified visual mapping.

Online mode performs exactly three public HTTPS GETs: branch version, asset
index, and CarColorLibrary. It never authenticates or reads gameplay data.
Offline mode accepts an original local ASTC bundle, with zero network calls.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Optional

from ..cdn import DEFAULT_BASE_URL
from ..database import AssetDatabase
from .dev29_public_cdn_forensics import (
    _BRANCH, _CDN_ORIGIN, _VERSION, _MAX_VERSION_BYTES,
    _MAX_DATABASE_BYTES, _MAX_ASSET_BYTES, _bounded_get, _json,
    PublicCDNProbeError,
)
from .dev36_latest_visual_ids import _load_local_fixture, _write_private_new
from ..visual_library_bundle import _extract

COLOR_ASSET = 'CarColorLibrary'


def parse_received_report(path: Path) -> dict[str, Any]:
    """Accept only the narrow sanitized Dev38 schema; discard all other keys."""
    doc = _load_local_fixture(path)
    if not isinstance(doc, dict) or doc.get('status') != 'received_roster_numeric_ids_absent_from_source_libraries':
        raise ValueError('not a Dev38 unmatched-ID report')
    branch, dbv = doc.get('source_branch'), doc.get('source_database_version')
    if type(branch) is not str or not _BRANCH.fullmatch(branch) or type(dbv) is not str or not _VERSION.fullmatch(dbv):
        raise ValueError('invalid Dev38 source identification')
    raw = doc.get('individual_absent_received_ids')
    coverage = doc.get('coverage_by_attribute')
    if not isinstance(raw, list) or len(raw) > 90 or not isinstance(coverage, dict):
        raise ValueError('invalid Dev38 ID list')
    paint = []
    seen = set()
    sum_all = 0
    for item in raw:
        if not isinstance(item, dict) or item.get('attribute') not in ('paint', 'interior', 'calliper'):
            raise ValueError('invalid unmatched-ID entry')
        slot, num, cnt = item['attribute'], item.get('received_numeric_id'), item.get('occurrences')
        tnr, other = item.get('tnr_model_syntax_occurrences'), item.get('other_or_unknown_model_occurrences')
        if any(type(v) is not int for v in (num, cnt, tnr, other)) or not (0 <= num <= 0x7fffffff and 1 <= cnt <= 30 and 0 <= tnr <= cnt and 0 <= other <= cnt and tnr + other == cnt):
            raise ValueError('invalid unmatched-ID counts')
        if (slot, num) in seen:
            raise ValueError('duplicate unmatched-ID')
        seen.add((slot, num))
        sum_all += cnt
        if slot == 'paint':
            paint.append({'received_paint_id': num, 'occurrences': cnt,
                          'tnr_model_syntax_occurrences': tnr,
                          'other_or_unknown_model_occurrences': other})
    if (type(doc.get('total_absent_received_occurrences')) is not int or
            sum_all != doc['total_absent_received_occurrences'] or
            type(doc.get('unique_attribute_id_pairs_absent')) is not int or
            len(raw) != doc['unique_attribute_id_pairs_absent']):
        raise ValueError('Dev38 summary mismatch')
    stats = coverage.get('paint')
    if not isinstance(stats, dict) or type(stats.get('absent_from_sources')) is not int or stats['absent_from_sources'] != sum(p['occurrences'] for p in paint):
        raise ValueError('Dev38 paint count mismatch')
    return {'branch': branch, 'database_version': dbv,
            'paint': sorted(paint, key=lambda item: item['received_paint_id'])}


def parse_palette(raw: bytes) -> tuple[dict[int, str], str]:
    """Preserve even unnamed entries (ordinary labeled export excludes them)."""
    if type(raw) is not bytes or not 64 <= len(raw) <= _MAX_ASSET_BYTES:
        raise ValueError('invalid palette source size')
    records = _extract(raw, COLOR_ASSET)
    return {ident: name for ident, name, _ in records}, hashlib.sha256(raw).hexdigest()


def fetch_current_palette(branch: str, *, session: Any) -> tuple[bytes, dict[str, Any]]:
    if type(branch) is not str or not _BRANCH.fullmatch(branch):
        raise ValueError('invalid branch')
    if DEFAULT_BASE_URL.rstrip('/') != _CDN_ORIGIN:
        raise PublicCDNProbeError('unexpected CDN origin')
    version_response = _json(_bounded_get(session, f'{_CDN_ORIGIN}/asset_database_{branch}.version', _MAX_VERSION_BYTES))
    if not isinstance(version_response, dict):
        raise PublicCDNProbeError('unexpected version document')
    dbv = str(version_response.get('version', ''))
    if not _VERSION.fullmatch(dbv):
        raise PublicCDNProbeError('invalid advertised version')
    raw_index = _bounded_get(session, f'{_CDN_ORIGIN}/asset_database.{dbv}.json', _MAX_DATABASE_BYTES)
    try:
        db = AssetDatabase.from_json(_json(raw_index))
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise PublicCDNProbeError('invalid index') from exc
    if str(db.version) != dbv:
        raise PublicCDNProbeError('database mismatch')
    asset = db.assets.get(COLOR_ASSET)
    if asset is None:
        raise PublicCDNProbeError('CarColorLibrary absent from index')
    version = str(asset.version)
    size = asset.size('ASTC')
    if not _VERSION.fullmatch(version) or type(size) is not int or not 64 <= size <= _MAX_ASSET_BYTES:
        raise PublicCDNProbeError('invalid palette version or size')
    raw = _bounded_get(session, f'{_CDN_ORIGIN}/ANDROID/ASTC/{COLOR_ASSET}.ASTC.{version}', min(size + 1, _MAX_ASSET_BYTES))
    if len(raw) != size:
        raise PublicCDNProbeError('palette size mismatch')
    parse_palette(raw)  # Validate complete native structure before accepting response.
    return raw, {'branch': branch, 'database_version': dbv,
                 'index_sha256': hashlib.sha256(raw_index).hexdigest(),
                 'palette_asset_version': version, 'network_requests': 3}


def compare_paint_to_palette(received: dict[str, Any], raw_palette: bytes,
                             *, evidence: dict[str, Any]) -> dict[str, Any]:
    palette, digest = parse_palette(raw_palette)
    rows = []
    for item in received['paint']:
        ident = item['received_paint_id']
        present = ident in palette
        rows.append({**item, 'present_in_color_palette': present,
                     'palette_name': palette[ident] or None if present else None,
                     'palette_record_is_unnamed': bool(present and not palette[ident]),
                     'paint_to_color_namespace_join_verified': False})
    return {
        'status': 'received_paint_id_vs_separate_color_palette_checked',
        'roster_source_branch': received['branch'],
        'roster_source_database_version': received['database_version'],
        'palette_source': COLOR_ASSET,
        'palette_branch': evidence.get('branch') or received['branch'],
        'palette_database_version': evidence.get('database_version'),
        'palette_asset_version': evidence.get('palette_asset_version'),
        'palette_index_sha256': evidence.get('index_sha256'),
        'palette_sha256': digest,
        'palette_record_count_including_unnamed': len(palette),
        'palette_unnamed_record_count': sum(not label for label in palette.values()),
        'same_database_version_as_roster_sources': (received['database_version'] == evidence.get('database_version')) if evidence.get('database_version') else None,
        'individual_unmatched_received_paint_ids': rows,
        'source_paint_library_absence_unchanged': True,
        'numeric_palette_overlap_is_not_paint_name_mapping': True,
        'id_zero_is_not_assumed_default': True,
        'mapping_promoted': False,
        'gameplay_read_count': 0,
        'authentication_used': False,
        'network_requests': evidence.get('network_requests', 0),
        'roster_or_player_identifiers_included': False,
    }


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description='Dev39: inspect missing received paint IDs in the separate public CarColorLibrary palette')
    p.add_argument('--received-report', help='sanitized Dev38 unmatched received-ID report')
    source = p.add_mutually_exclusive_group()
    source.add_argument('--online', action='store_true', help='opt in to exactly three public CDN GETs')
    source.add_argument('--color-bundle', help='existing original CarColorLibrary.ASTC.* file; zero requests')
    p.add_argument('--branch', default=None, help='selected branch, must agree with Dev38 report')
    p.add_argument('--output', help='write result to a new local JSON file')
    args = p.parse_args(argv)
    if args.output and (Path(args.output).exists() or Path(args.output).is_symlink() or not Path(args.output).parent.is_dir()):
        p.error('output must be new in an existing directory')
    if not args.online and not args.color_bundle:
        print(json.dumps({'status':'dev39_dry_run', 'network_requests':0, 'planned_public_gets':3,
                          'gameplay_read_count':0, 'authentication_used':False}, indent=2))
        return 0
    if not args.received_report:
        p.error('--received-report is required for a palette comparison')
    try:
        received = parse_received_report(Path(args.received_report))
        branch = args.branch or received['branch']
        if branch != received['branch'] or not _BRANCH.fullmatch(branch):
            raise ValueError('branch must agree with received roster report')
        if args.online:
            import requests
            with requests.Session() as session:
                session.trust_env = False
                raw, evidence = fetch_current_palette(branch, session=session)
        else:
            path = Path(args.color_bundle)
            if path.is_symlink() or not path.is_file() or not 64 <= path.stat().st_size <= _MAX_ASSET_BYTES:
                raise ValueError('invalid local palette source')
            raw = path.read_bytes()
            evidence = {'branch': branch, 'database_version': None, 'network_requests': 0}
        result = compare_paint_to_palette(received, raw, evidence=evidence)
        if args.output:
            _write_private_new(Path(args.output), result)
    except Exception:
        print(json.dumps({'status':'dev39_validation_unavailable', 'details':'suppressed',
                          'mapping_promoted':False, 'gameplay_read_count':0}))
        return 3
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
