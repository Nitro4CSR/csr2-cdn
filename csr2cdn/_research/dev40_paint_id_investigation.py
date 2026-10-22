"""Dev40: evidence-linked analysis of unresolved *received* paint IDs.

- Uses sanitized Dev38 and Dev39 reports plus validated Dev36 public catalogue.
- An explicit operator approval may label paint ID 0 as 'Transparent' for display.
  This is NEVER a verified join to CarColorLibrary or a production paint mapping.
- Optionally probes CarWrapLibrary from the public CDN (3 GETs, no gameplay).
  Wrap IDs are a SEPARATE namespace, not alternative paint labels.
- All file outputs are new private local files; no input raw roster needed.
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
    _BRANCH, _CDN_ORIGIN, _VERSION, _MAX_ASSET_BYTES,
    _MAX_DATABASE_BYTES, _MAX_VERSION_BYTES, _bounded_get, _json,
    PublicCDNProbeError,
)
from .dev36_latest_visual_ids import _write_private_new
from .dev37_source_id_lookup import _read_json, load_catalog, index_and_gaps
from .dev39_color_palette_overlap import parse_received_report
from ..visual_library_bundle import decode_visual_unityfs

_WRAP_ASSET = 'CarWrapLibrary'
_MAX_REPORT = 128 * 1024


def validate_evidence(received_path: Path, palette_path: Path,
                      catalogue_path: Path, summary_path: Path):
    """Fail closed on mixed database snapshots or contradictory ID evidence."""
    received = parse_received_report(received_path)
    raw_received = _read_json(received_path, _MAX_REPORT)
    palette = _read_json(palette_path, _MAX_REPORT)
    meta, rows = load_catalog(catalogue_path, summary_path)
    if not isinstance(palette, dict) or palette.get('status') != 'received_paint_id_vs_separate_color_palette_checked':
        raise ValueError('invalid Dev39 overlap report')
    if received['branch'] != meta['branch'] or received['database_version'] != meta['database_version']:
        raise ValueError('received catalogue version mismatch')
    if raw_received.get('source_sha256') != meta['source_sha256']:
        raise ValueError('received cosmetic source fingerprint mismatch')
    if (palette.get('roster_source_branch') != received['branch'] or
        palette.get('roster_source_database_version') != received['database_version'] or
        palette.get('palette_branch') != received['branch'] or
        palette.get('palette_database_version') != received['database_version'] or
        palette.get('same_database_version_as_roster_sources') is not True or
        palette.get('source_paint_library_absence_unchanged') is not True or
        palette.get('numeric_palette_overlap_is_not_paint_name_mapping') is not True or
        palette.get('mapping_promoted') is not False or
        palette.get('gameplay_read_count') != 0 or
        palette.get('authentication_used') is not False):
        raise ValueError('mixed or unverified palette evidence')
    actual = palette.get('individual_unmatched_received_paint_ids')
    if not isinstance(actual, list) or len(actual) != len(received['paint']):
        raise ValueError('missing or duplicated unmatched paint IDs in palette evidence')
    checked = {}
    for item in actual:
        if not isinstance(item, dict):
            raise ValueError('invalid palette row')
        ident = item.get('received_paint_id')
        if type(ident) is not int or ident in checked or type(item.get('present_in_color_palette')) is not bool:
            raise ValueError('duplicate or invalid palette ID')
        name = item.get('palette_name')
        if name is not None and (type(name) is not str or not 1 <= len(name) <= 180):
            raise ValueError('invalid palette label')
        if item.get('paint_to_color_namespace_join_verified') is not False:
            raise ValueError('unsupported palette-to-paint claim')
        checked[ident] = item
    for item in received['paint']:
        original = checked.get(item['received_paint_id'])
        if original is None or any(original.get(k) != v for k, v in item.items()):
            raise ValueError('palette counts or membership differ from received report')
    idx, _, _ = index_and_gaps(rows)
    for item in received['paint']:
        if idx.get(('paint', item['received_paint_id'])):
            raise ValueError('a reported missing paint ID is in the validated paint catalogue')
    return received, palette, meta, idx, checked


def fetch_current_wrap(branch: str, *, session: Any) -> tuple[bytes, dict[str, Any]]:
    """One selected current-branch wrap bundle, two index GETs: exactly 3 GETs."""
    if type(branch) is not str or not _BRANCH.fullmatch(branch):
        raise ValueError('invalid branch')
    if DEFAULT_BASE_URL.rstrip('/') != _CDN_ORIGIN:
        raise PublicCDNProbeError('unexpected CDN origin')
    version_doc = _json(_bounded_get(session, f'{_CDN_ORIGIN}/asset_database_{branch}.version', _MAX_VERSION_BYTES))
    if not isinstance(version_doc, dict):
        raise PublicCDNProbeError('invalid version document')
    dbv = str(version_doc.get('version', ''))
    if not _VERSION.fullmatch(dbv):
        raise PublicCDNProbeError('invalid advertised database')
    index_bytes = _bounded_get(session, f'{_CDN_ORIGIN}/asset_database.{dbv}.json', _MAX_DATABASE_BYTES)
    try:
        db = AssetDatabase.from_json(_json(index_bytes))
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise PublicCDNProbeError('invalid database index') from exc
    if str(db.version) != dbv:
        raise PublicCDNProbeError('database/index mismatch')
    asset = db.assets.get(_WRAP_ASSET)
    if asset is None:
        raise PublicCDNProbeError('wrap source absent from index')
    assetv = str(asset.version)
    size = asset.size('ASTC')
    if not _VERSION.fullmatch(assetv) or type(size) is not int or not 64 <= size <= _MAX_ASSET_BYTES:
        raise PublicCDNProbeError('invalid wrap size or version')
    raw = _bounded_get(session, f'{_CDN_ORIGIN}/ANDROID/ASTC/{_WRAP_ASSET}.ASTC.{assetv}', min(size + 1, _MAX_ASSET_BYTES))
    if len(raw) != size:
        raise PublicCDNProbeError('wrap size mismatch')
    decode_visual_unityfs(raw, library=_WRAP_ASSET)
    return raw, {'database_version': dbv, 'branch': branch, 'asset_version': assetv,
                 'index_sha256': hashlib.sha256(index_bytes).hexdigest(), 'network_requests': 3}


def analyze(received: dict[str, Any], palette: dict[str, Any], meta: dict[str, Any],
            idx: dict[tuple[str,int], list[dict[str,Any]]], checked: dict[int,dict[str, Any]],
            *, accept_transparent_zero: bool, wrap_bytes: Optional[bytes] = None,
            wrap_evidence: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    wrap_labels: dict[int, str] = {}
    if wrap_bytes is not None:
        wraps = decode_visual_unityfs(wrap_bytes, library=_WRAP_ASSET)
        wrap_labels = {r.code: r.name for r in wraps.records}
    evidence = wrap_evidence or {}
    rows = []
    for item in received['paint']:
        ident = item['received_paint_id']
        palette_row = checked[ident]
        name = palette_row.get('palette_name')
        present = palette_row['present_in_color_palette']
        approved = bool(accept_transparent_zero and ident == 0 and present and name == 'Transparent')
        other = [
            {'attribute': slot, 'source_library': r['source_library'], 'source_label': r['source_label']}
            for slot in ('interior', 'calliper') for r in idx.get((slot, ident), [])
        ]
        rows.append({
            'attribute': 'paint', 'received_numeric_id': ident,
            'occurrences': item['occurrences'],
            'tnr_model_syntax_occurrences': item['tnr_model_syntax_occurrences'],
            'other_or_unknown_model_occurrences': item['other_or_unknown_model_occurrences'],
            'paint_library_status': 'absent_from_both_paint_libraries',
            'separate_color_palette': {'present': present, 'name': name},
            'operator_approved_display_label': 'Transparent' if approved else None,
            'display_label_source': 'user_approved_palette_overlap_not_verified_paint_join' if approved else None,
            'other_attribute_matches_not_paint': other,
            'wrap_source': ({'checked': True, 'present': ident in wrap_labels,
                             'name': wrap_labels.get(ident), 'not_paint_mapping': True}
                            if wrap_bytes is not None else {'checked': False}),
            'paint_to_palette_join_verified': False,
            'paint_visual_meaning_verified': False,
            'production_mapping_promoted': False,
        })
    return {
        'status': 'dev40_received_paint_id_evidence_classified',
        'branch': meta['branch'], 'roster_source_database_version': meta['database_version'],
        'palette_asset_version': palette.get('palette_asset_version'),
        'palette_sha256': palette.get('palette_sha256'),
        'wrap_asset_version': evidence.get('asset_version'),
        'wrap_source_database_version': evidence.get('database_version'),
        'wrap_source_sha256': hashlib.sha256(wrap_bytes).hexdigest() if wrap_bytes is not None else None,
        'wrap_source_same_database_as_roster': (evidence.get('database_version') == meta['database_version']
                                                if evidence.get('database_version') else None),
        'individual_received_paint_ids': rows,
        'unique_unmatched_paint_ids': len(rows),
        'unmatched_paint_occurrences': sum(x['occurrences'] for x in rows),
        'transparent_zero_operator_acceptance_explicit': accept_transparent_zero,
        'operator_approved_labels_are_not_verified_library_mappings': True,
        'raw_roster_or_player_ids_included': False,
        'production_mapping_promoted': False,
        'network_requests': evidence.get('network_requests', 0),
        'authentication_used': False, 'gameplay_read_count': 0,
    }


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description='Dev40: interpret received paint IDs 0/15 without treating palette/wrap IDs as paint mappings')
    p.add_argument('--received-report', type=Path, required=True, help='sanitized Dev38 report')
    p.add_argument('--palette-report', type=Path, required=True, help='matching Dev39 report')
    p.add_argument('--catalog', type=Path, required=True, help='Dev36 source-IDs catalogue')
    p.add_argument('--summary', type=Path, required=True, help='matching Dev36 summary')
    p.add_argument('--accept-transparent-zero', action='store_true', help='explicitly use user-approved Transparent display label for ID 0')
    source = p.add_mutually_exclusive_group()
    source.add_argument('--online-wrap', action='store_true', help='exactly 3 public GETs to check CarWrapLibrary, no gameplay')
    source.add_argument('--wrap-bundle', type=Path, help='locally saved original wrap bundle; 0 network requests')
    p.add_argument('--output', type=Path, help='NEW local result JSON')
    args = p.parse_args(argv)
    if args.output and (args.output.exists() or args.output.is_symlink() or not args.output.parent.is_dir()):
        p.error('output must be new in an existing directory')
    try:
        received, palette, meta, idx, checked = validate_evidence(
            args.received_report, args.palette_report, args.catalog, args.summary)
        raw = None
        wrap_evidence: dict[str, Any] = {}
        if args.online_wrap:
            import requests
            with requests.Session() as session:
                session.trust_env = False
                raw, wrap_evidence = fetch_current_wrap(received['branch'], session=session)
        elif args.wrap_bundle is not None:
            path = args.wrap_bundle
            if path.is_symlink() or not path.is_file() or not 64 <= path.stat().st_size <= _MAX_ASSET_BYTES:
                raise ValueError('invalid local wrap bundle')
            raw = path.read_bytes()
            wrap_evidence = {'network_requests': 0}
        result = analyze(received, palette, meta, idx, checked,
                         accept_transparent_zero=args.accept_transparent_zero,
                         wrap_bytes=raw, wrap_evidence=wrap_evidence)
        if args.output:
            _write_private_new(args.output, result)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except (Exception, KeyboardInterrupt):
        print(json.dumps({'status': 'dev40_evidence_unavailable', 'details': 'suppressed',
                          'gameplay_read_count': 0, 'production_mapping_promoted': False}))
        return 3


if __name__ == '__main__':
    raise SystemExit(main())
