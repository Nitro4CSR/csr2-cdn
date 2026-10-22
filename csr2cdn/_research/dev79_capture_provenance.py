"""Dev79: fail-closed offline stage-manifest consistency checks for Dev78 snapshots.

A manifest is an untrusted, self-reported companion file. Matching hashes and
ordered stage markers cannot authenticate the capturing process or live game.
No gameplay code is executed. Production mappings are never promoted.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Any

from .dev77_gacha_config_validity import inspect as inspect_dev77
from .dev78_runtime_paint_snapshot import _parse_json, validate_snapshot

_SCHEMA = 'csr2cdn.dev79.stage-manifest.v1'
_MAX_BYTES = 131072
_MAX_EVENTS = 4
_STAGE_ANCHORS = {
    'gacha_gate': '0x36126F4',
    'paint_lookup': '0x380B648',
    'profile_update': '0x34E8988',
    'paint_post_refresh': '0x380B648',
}
_STAGE_ORDER = tuple(_STAGE_ANCHORS)
_HEX64 = re.compile(r'[0-9a-f]{64}\Z')
_CAPTURE_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z')


def _obj(value: Any, context: str, required: set[str], optional: set[str] = frozenset()) -> dict[str, Any]:
    if type(value) is not dict:
        raise ValueError(context + ': expected object')
    if required - value.keys():
        raise ValueError(context + ': missing required fields')
    if value.keys() - required - optional:
        raise ValueError(context + ': unrecognized fields')
    return value


def _hex(value: Any, context: str) -> str:
    if type(value) is not str or not _HEX64.fullmatch(value):
        raise ValueError(context + ': expected lowercase SHA-256 hex digest')
    return value


def canonical_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True)
    return hashlib.sha256(payload.encode('ascii')).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def read_bounded_json(path: Path) -> tuple[dict[str, Any], bytes]:
    """Read a regular local JSON file, rejecting symbolic-link inputs."""
    flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0)
    try:
        before = os.lstat(path)
        if not stat.S_ISREG(before.st_mode):
            raise ValueError('input must be a regular file')
        fd = os.open(path, flags)
        with os.fdopen(fd, 'rb') as stream:
            opened = os.fstat(stream.fileno())
            if (not stat.S_ISREG(opened.st_mode)
                    or not os.path.samestat(before, opened)
                    or not os.path.samestat(os.lstat(path), opened)):
                raise ValueError('input must be a regular file')
            data = stream.read(_MAX_BYTES + 1)
    except OSError as exc:
        raise ValueError('cannot read regular local input') from exc
    if len(data) > _MAX_BYTES:
        raise ValueError('input exceeds 128 KiB')
    try:
        content = _parse_json(data.decode('utf-8'))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError('input must be strict UTF-8 JSON') from exc
    if type(content) is not dict:
        raise ValueError('input must be a JSON object')
    return content, data


def validate_manifest(snapshot: dict[str, Any], raw_snapshot: bytes,
                      manifest: dict[str, Any], apk_sha256: str) -> dict[str, Any]:
    """Validate cross-file/internal claims, not independent runtime provenance."""
    snap_assessment = validate_snapshot(snapshot)
    manifest = _obj(manifest, 'manifest',
                    {'schema', 'snapshot_sha256', 'apk_sha256', 'capture', 'events'})
    if manifest['schema'] != _SCHEMA:
        raise ValueError('manifest: unsupported schema')
    if _hex(manifest['snapshot_sha256'], 'snapshot_sha256') != hashlib.sha256(raw_snapshot).hexdigest():
        raise ValueError('manifest: raw snapshot SHA-256 mismatch')
    if _hex(manifest['apk_sha256'], 'apk_sha256') != _hex(apk_sha256, 'expected apk_sha256'):
        raise ValueError('manifest: APK SHA-256 mismatch')
    cap = _obj(manifest['capture'], 'capture',
        {'capture_id', 'kind', 'method', 'no_replayed_gameplay_calls', 'session_continuity_claimed'})
    if type(cap['capture_id']) is not str or not _CAPTURE_ID.fullmatch(cap['capture_id']):
        raise ValueError('capture_id: expected opaque 1-64 character label')
    kind = snapshot['capture']['kind']
    if cap['kind'] != kind:
        raise ValueError('manifest: capture kind does not match snapshot')
    expected_method = 'synthetic_fixture' if kind == 'synthetic' else 'read_only_observation'
    if cap['method'] != expected_method:
        raise ValueError('manifest: incompatible capture method')
    for key in ('no_replayed_gameplay_calls', 'session_continuity_claimed'):
        if type(cap[key]) is not bool or cap[key] is not True:
            raise ValueError('capture: manifest requires positive non-mutating continuity claims')
    if snapshot['capture']['non_mutating'] is not True:
        raise ValueError('capture: snapshot must claim non-mutating acquisition')
    events = manifest['events']
    if type(events) is not list or not 1 <= len(events) <= _MAX_EVENTS:
        raise ValueError('events: expected 1-4 stage observations')
    expected_stages = []
    paint = snapshot.get('paint') or {}
    if 'gacha' in snapshot:
        expected_stages.append('gacha_gate')
    if paint.get('lookup') is not None:
        expected_stages.append('paint_lookup')
    if paint.get('post_refresh') is not None:
        expected_stages.extend(['profile_update', 'paint_post_refresh'])
    if not expected_stages:
        raise ValueError('manifest: no observed gacha or paint stage in snapshot')
    seen: list[str] = []
    last_sequence = -1
    last_tick = -1
    for event in events:
        evt = _obj(event, 'event', {'stage', 'sequence', 'monotonic_tick', 'native_rva'},
                   {'section_sha256'})
        stage = evt['stage']
        if type(stage) is not str or stage not in _STAGE_ANCHORS:
            raise ValueError('event: unknown stage')
        if evt['native_rva'] != _STAGE_ANCHORS[stage]:
            raise ValueError('event: native RVA does not match pinned observation point')
        sequence = evt['sequence']
        tick = evt['monotonic_tick']
        if type(sequence) is not int or not 0 <= sequence <= 1_000_000:
            raise ValueError('event: invalid sequence')
        if type(tick) is not int or not 0 <= tick <= (1 << 63) - 1:
            raise ValueError('event: invalid monotonic tick')
        if sequence <= last_sequence or tick <= last_tick:
            raise ValueError('event: sequence and tick must increase strictly')
        last_sequence, last_tick = sequence, tick
        data = None
        if stage == 'gacha_gate':
            data = snapshot.get('gacha')
        elif stage == 'paint_lookup':
            data = paint.get('lookup')
        elif stage == 'paint_post_refresh':
            data = paint.get('post_refresh')
        if data is None:
            if 'section_sha256' in evt:
                raise ValueError('event: unbound section digest')
        elif _hex(evt.get('section_sha256'), 'section_sha256') != canonical_hash(data):
            raise ValueError('event: stage payload digest mismatch')
        seen.append(stage)
    if seen != expected_stages:
        raise ValueError('event: missing, repeated, or out-of-order observation stages')
    return {
        'manifest_schema': _SCHEMA,
        'manifest_sha256': canonical_hash(manifest),
        'raw_snapshot_sha256_matches': True,
        'local_apk_sha256_matches': True,
        'all_stage_payload_sha256_match': True,
        'stage_order_and_ticks_consistent': True,
        'native_rva_stage_anchors_match_pinned_locations': True,
        'stages_claimed': seen,
        'claimed_single_session_continuity': cap['session_continuity_claimed'],
        'claimed_no_replayed_gameplay_calls': cap['no_replayed_gameplay_calls'],
        'capture_label_sha256': hashlib.sha256(cap['capture_id'].encode('utf-8')).hexdigest(),
        'capture_kind': kind,
        'status': ('synthetic_stage_manifest_consistent_not_runtime_evidence' if kind == 'synthetic'
                   else 'self_reported_stage_manifest_consistent_not_authenticated'),
        'external_capture_origin_independently_authenticated': False,
        'game_execution_stage_alignment_independently_verified': False,
        'production_paint_mapping_verified': False,
        'production_mappings_changed': False,
        'snapshot_assessment': snap_assessment,
    }


def assess(apk: Path, snapshot_path: Path | None = None,
           manifest_path: Path | None = None) -> dict[str, Any]:
    if manifest_path is not None and snapshot_path is None:
        raise ValueError('--manifest requires --snapshot')
    static = inspect_dev77(apk)
    if static['production_mappings_changed'] or static['runtime_ordered_paint_list_captured']:
        raise ValueError('pinned Dev77 native-only guard changed')
    snapshot = raw = manifest = None
    if snapshot_path is not None:
        snapshot, raw = read_bounded_json(snapshot_path)
        snap_assessment = validate_snapshot(snapshot)
    else:
        snap_assessment = None
    manifest_assessment = None
    if manifest_path is not None:
        manifest, _ = read_bounded_json(manifest_path)
        manifest_assessment = validate_manifest(snapshot, raw, manifest, sha256_file(apk))
    return {
        'status': 'dev79_offline_stage_manifest_validator',
        'client': 'CSR2 6.8.0',
        'previous_dev72_77_pinned_native_chain_passed': True,
        'dev77_config_validity_native_sha256': static['native_method']['sha256'],
        'snapshot_supplied': snapshot is not None,
        'snapshot_assessment': snap_assessment,
        'stage_manifest_supplied': manifest is not None,
        'stage_manifest_assessment': manifest_assessment,
        'missing_capture_artifacts': (['runtime_snapshot', 'stage_manifest'] if snapshot is None
                                      else ['stage_manifest'] if manifest is None else []),
        'conditional_index_15_paint_candidate': 1323,
        'paint_index_0_runtime_mapping_verified': False,
        'production_paint_mapping_verified': False,
        'production_mappings_changed': False,
        'network_requests': 0,
        'authenticated_gameplay_requests': 0,
        'gameplay_state_writes': 0,
        'private_capture_echoed_to_report': False,
        'provenance_limitation': 'Self-reported manifest and digest matches do not authenticate gameplay or physical capture origin.',
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apk', type=Path, required=True)
    parser.add_argument('--snapshot', type=Path)
    parser.add_argument('--manifest', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output.exists() or args.output.is_symlink():
        parser.error('refusing to overwrite existing evidence output')
    try:
        result = assess(args.apk, args.snapshot, args.manifest)
        body = json.dumps(result, sort_keys=True, ensure_ascii=True, indent=2) + '\n'
        if len(body.encode('utf-8')) > 150_000:
            raise ValueError('report exceeds size limit')
        with args.output.open('x', encoding='utf-8') as stream:
            stream.write(body)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    print('Dev79: offline manifest validation complete; no production mapping promoted.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
