"""Dev30 opt-in public-source cache and zero-network namespace re-audit.

This tool saves *only* already validated public visual bundles when explicitly
requested. It never accesses account or gameplay endpoints. Bundles are not
included in the package or printed. Cache contents must be treated as game
publisher assets and distributed only if separately authorized.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Optional

from .dev29_public_cdn_forensics import (
    _ALLOWED, _BRANCH, _MAX_ASSET_BYTES, validate_public_tnr_sources,
)
from .dev25_visual_forensics import audit_tnr_eligibility_source
from .dev27_native_wheel_forensics import audit_tuner_rim_source, extract_private_rim_source_fields

_CACHE_SCHEMA = 1
_MAX_MANIFEST_BYTES = 16 * 1024
_MAX_BASELINE_BYTES = 128 * 1024


def _hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _source_name(slot: str) -> str:
    return _ALLOWED[slot] + '.ASTC'


def _write_json_exclusive(path: Path, value: dict[str, Any]) -> None:
    with path.open('x', encoding='utf-8') as out:
        json.dump(value, out, indent=2, sort_keys=True)
        out.write('\n')


def save_validated_public_cache(directory: Path, bundles: dict[str, bytes],
                                audit: dict[str, Any]) -> dict[str, Any]:
    """Commit a complete source set in a new directory, without overwrites.

    The network fetch and canonical parsing must already have completed.
    Verifies the exact SHA-256 from that audit again before persisting.
    """
    directory = Path(directory)
    if directory.exists() or not directory.parent.is_dir() or directory.is_symlink():
        raise ValueError('cache must be a new directory in an existing parent')
    if audit.get('status') != 'public_cdn_source_validation_completed':
        raise ValueError('not a validated public source report')
    slots = audit.get('requested_slots')
    if (not isinstance(slots, list) or not slots or
            len(slots) != len(set(slots)) or any(x not in _ALLOWED for x in slots) or
            audit.get('unavailable_slots') or set(bundles) != set(slots) or
            set(audit.get('validated_source_sha256', {})) != set(slots)):
        raise ValueError('incomplete public source capture')
    branch = audit.get('branch')
    if not isinstance(branch, str) or not _BRANCH.fullmatch(branch):
        raise ValueError('invalid public release')
    manifest = {
        'schema': _CACHE_SCHEMA,
        'source': 'public_cdn_validated_original_bundles_not_roster',
        'branch': branch,
        'database_version': audit['database_version'],
        'public_index_sha256': audit['public_index_sha256'],
        'slots': {},
    }
    for slot in slots:
        raw = bundles[slot]
        if (type(raw) is not bytes or not 64 <= len(raw) <= _MAX_ASSET_BYTES or
                _hash(raw) != audit['validated_source_sha256'][slot]):
            raise ValueError('source capture disagrees with validated public audit')
        manifest['slots'][slot] = {'file': _source_name(slot), 'sha256': _hash(raw),
                                   'size_bytes': len(raw)}
    # Stage a complete cache on same filesystem. Only atomic final rename
    # exposes it. Existing destination is never intentionally overwritten.
    with tempfile.TemporaryDirectory(prefix='.dev30-public-sources-', dir=directory.parent) as tmp:
        temp = Path(tmp)
        for slot in slots:
            with (temp / _source_name(slot)).open('xb') as stream:
                stream.write(bundles[slot])
        _write_json_exclusive(temp / 'manifest.json', manifest)
        if directory.exists():
            raise ValueError('cache destination became occupied')
        temp.rename(directory)
    return {
        'status': 'validated_public_source_cache_created',
        'local_bundle_count': len(slots),
        'branch': branch,
        'database_version': audit['database_version'],
        'source_sha256': dict(audit['validated_source_sha256']),
        'authentication_used': False,
        'gameplay_read_count': 0,
        'player_data_saved': False,
        'candidate_names_trusted': False,
        'wheel_mappings_accepted': False,
        'names_or_numeric_ids_in_report': False,
    }


def _bounded_local_file(path: Path, limit: int) -> bytes:
    if path.is_symlink() or not path.is_file() or not 1 <= path.stat().st_size <= limit:
        raise ValueError('local source file is missing, linked or oversized')
    return path.read_bytes()


def replay_public_cache(directory: Path, *, baseline_audit: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Reverify SHA and canonical native structure with zero network calls.

    Namespace comparisons inspect original source strings IN MEMORY but only
    report aggregate lexical overlaps, never names, identifiers or joins.
    """
    directory = Path(directory)
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError('local source directory unavailable')
    manifest = json.loads(_bounded_local_file(directory / 'manifest.json', _MAX_MANIFEST_BYTES))
    if (type(manifest) is not dict or manifest.get('schema') != _CACHE_SCHEMA or
            manifest.get('source') != 'public_cdn_validated_original_bundles_not_roster' or
            not isinstance(manifest.get('branch'), str) or not _BRANCH.fullmatch(manifest['branch']) or
            type(manifest.get('slots')) is not dict or not manifest['slots'] or
            not set(manifest['slots']).issubset(_ALLOWED)):
        raise ValueError('invalid public source cache manifest')
    audits: dict[str, Any] = {}
    hashes: dict[str, str] = {}
    for slot, row in manifest['slots'].items():
        if type(row) is not dict or row.get('file') != _source_name(slot):
            raise ValueError('unrecognized local source path')
        raw = _bounded_local_file(directory / _source_name(slot), _MAX_ASSET_BYTES)
        if (type(row.get('size_bytes')) is not int or len(raw) != row['size_bytes'] or
                row.get('sha256') != _hash(raw)):
            raise ValueError('source digest or size changed')
        audits[slot] = (audit_tuner_rim_source(raw) if slot == 'rim' else
                        audit_tnr_eligibility_source(raw, library=_ALLOWED[slot]))
        hashes[slot] = _hash(raw)
    result: dict[str, Any] = {
        'status': 'cached_public_sources_revalidated_offline',
        'branch': manifest['branch'],
        'database_version': manifest['database_version'],
        'source_sha256': hashes,
        'audited_slots': audits,
        'network_requests': 0,
        'gameplay_read_count': 0,
        'roster_used': False,
        'raw_source_names_or_numeric_ids_exposed': False,
        'lexical_overlap_is_roster_join': False,
        'compatibility_rules_verified': False,
        'mappings_promoted': False,
    }
    if baseline_audit is not None:
        if not isinstance(baseline_audit, dict):
            raise ValueError('baseline must be a JSON object')
        prior = baseline_audit.get('validated_source_sha256', {})
        if not isinstance(prior, dict):
            raise ValueError('invalid baseline source hash field')
        same_slot_hashes = {slot: prior.get(slot) == value for slot, value in hashes.items()}
        same_branch = baseline_audit.get('branch') == manifest['branch']
        same_database = (str(baseline_audit.get('database_version')) ==
                         str(manifest['database_version']))
        same_index = baseline_audit.get('public_index_sha256') == manifest['public_index_sha256']
        # Dev29 baselines can validate subsets; require exact slot coverage,
        # not merely agreement of whatever keys happened to be included.
        same_slot_coverage = set(prior) == set(hashes)
        baseline_is_validated = baseline_audit.get('status') == 'public_cdn_source_validation_completed'
        all_match = (baseline_is_validated and same_branch and same_database and
                     same_index and same_slot_coverage and all(same_slot_hashes.values()))
        result['dev29_baseline_comparison'] = {
            'same_branch': same_branch,
            'same_database_version': same_database,
            'same_public_index_sha256': same_index,
            'same_source_sha256_by_slot': same_slot_hashes,
            'same_source_slot_coverage': same_slot_coverage,
            'baseline_is_validated_public_audit': baseline_is_validated,
            'all_reported_source_bytes_and_index_match_baseline': all_match,
            'matching_source_hashes_confirm_same_bytes_not_eligibility': all_match,
            'baseline_comparison_is_mapping_or_eligibility_evidence': False,
        }
    return result


def export_private_local_rim_fields(directory: Path, output: Path,
                                    *, replay_result: dict[str, Any]) -> None:
    """Opt-in private source inspection, only after SHA-verified offline replay.

    Source strings are written to one new local file, NEVER returned in the
    public replay JSON or printed by the CLI. A second SHA verification guards
    against changed cache bytes between the replay and the private extraction.
    """
    output = Path(output)
    if (output.exists() or output.is_symlink() or not output.parent.is_dir()):
        raise ValueError('private source export requires a new local output file')
    digest = replay_result.get('source_sha256', {}).get('rim')
    if (replay_result.get('status') != 'cached_public_sources_revalidated_offline' or
            type(digest) is not str or len(digest) != 64):
        raise ValueError('a successful replay containing the rim source is required')
    raw = _bounded_local_file(Path(directory) / _source_name('rim'), _MAX_ASSET_BYTES)
    if _hash(raw) != digest:
        raise ValueError('rim bundle changed since verification')
    private = extract_private_rim_source_fields(raw)
    private['source_sha256'] = digest
    private['privacy_warning'] = 'Contains original publisher source names; keep private and do not publish.'
    # The private export must not use the standard 0666-mask JSON writer.
    # O_EXCL prevents overwrite and mode 0600 limits access on POSIX systems.
    fd = os.open(output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(private, stream, indent=2, ensure_ascii=False)
            stream.write('\n')
    except BaseException:
        output.unlink(missing_ok=True)
        raise


def capture_public_sources(branch: str, slots: tuple[str, ...], directory: Path,
                           *, session: Any) -> dict[str, Any]:
    """Exactly the bounded Dev29 allowlist / GET budget, plus opt-in capture."""
    # Validate destination before making any requests.
    directory = Path(directory)
    if directory.exists() or not directory.parent.is_dir():
        raise ValueError('capture target must not exist')
    captured: dict[str, bytes] = {}
    report = validate_public_tnr_sources(
        branch, slots=slots, session=session,
        validated_asset_sink=lambda slot, raw: captured.__setitem__(slot, raw))
    summary = save_validated_public_cache(directory, captured, report)
    return {'validation': report, 'local_cache': summary}


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description='Dev30 read-only public source cache/replay; offline default')
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument('--online', action='store_true', help='explicitly opt in to public CDN GETs')
    actions.add_argument('--replay-dir', type=Path, help='existing, validated local source cache (no network)')
    parser.add_argument('--branch', help='explicit release branch for --online')
    parser.add_argument('--slot', action='append', choices=tuple(_ALLOWED), default=[],
                        help='public source slot for --online, repeat up to four')
    parser.add_argument('--save-dir', type=Path, help='NEW directory to save validated source bundles')
    parser.add_argument('--baseline-audit', type=Path, help='existing bounded Dev29 JSON audit for offline hash comparison')
    parser.add_argument('--output', type=Path, help='NEW report JSON file (never overwrites)')
    parser.add_argument('--private-rim-fields-output', type=Path,
                        help='OPT-IN NEW PRIVATE local file with original rim strings; replay only')
    args = parser.parse_args(argv)
    if args.output and (args.output.exists() or not args.output.parent.is_dir()):
        parser.error('--output requires a new file in an existing directory')
    if (len(args.slot) != len(set(args.slot)) or len(args.slot) > 4):
        parser.error('duplicate or too many slots')
    if args.private_rim_fields_output and not args.replay_dir:
        parser.error('--private-rim-fields-output requires --replay-dir')
    if args.replay_dir:
        if args.branch or args.slot or args.save_dir is not None:
            parser.error('offline replay does not accept online options')
    elif args.online:
        if not args.branch or not _BRANCH.fullmatch(args.branch) or not args.slot or not args.save_dir:
            parser.error('--online requires a valid --branch, slots and a new --save-dir')
        if args.baseline_audit:
            parser.error('--baseline-audit requires --replay-dir')
    elif args.branch or args.save_dir or args.baseline_audit:
        parser.error('dry-run does not accept data access arguments')
    try:
        if args.replay_dir:
            baseline = None
            if args.baseline_audit:
                baseline = json.loads(_bounded_local_file(args.baseline_audit, _MAX_BASELINE_BYTES))
            result = replay_public_cache(args.replay_dir, baseline_audit=baseline)
            if args.private_rim_fields_output:
                export_private_local_rim_fields(args.replay_dir, args.private_rim_fields_output,
                                                replay_result=result)
        elif args.online:
            import requests  # no network-capable imports on dry-run or replay
            with requests.Session() as session:
                session.trust_env = False
                result = capture_public_sources(args.branch, tuple(args.slot), args.save_dir, session=session)
        else:
            result = {'status': 'dry_run_no_requests', 'network_requests': 0,
                      'online_requires_explicit_opt_in': True, 'gameplay_read_count': 0}
        if args.output:
            _write_json_exclusive(args.output, result)
        print(json.dumps(result, indent=2))
        return 0
    except (Exception, KeyboardInterrupt):
        # Never echo source bytes, local paths or exception strings. Source and
        # trust state are unchanged if a cache or source read fails.
        print(json.dumps({'status': 'source_validation_unavailable',
                          'no_mappings_changed': True}))
        return 3


if __name__ == '__main__':
    raise SystemExit(main())
