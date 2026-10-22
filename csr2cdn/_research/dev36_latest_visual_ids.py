"""Dev36: bounded public CDN current-branch cosmetic-ID audit.

Fetch the database version advertised *now* by an explicitly chosen release
branch, then retrieve the current six standard/TNR cosmetic libraries exactly
once. Original public labels and IDs are exported only by explicit opt-in.

Important: a public source catalogue cannot identify missing roster IDs.
An optional, already-saved own-crew + crew-members pair is needed to enumerate
unresolved paint/interior numeric IDs; no gameplay requests are made.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Optional

from ..cdn import DEFAULT_BASE_URL
from ..database import AssetDatabase
from .dev29_public_cdn_forensics import (
    _BRANCH, _CDN_ORIGIN, _VERSION, _MAX_ASSET_BYTES,
    _MAX_DATABASE_BYTES, _MAX_VERSION_BYTES, _bounded_get, _json,
    PublicCDNProbeError,
)
from .dev25_visual_forensics import diagnose_paint_interior_gaps
from ..game_labels import GameVisualLibrary, VisualCodeName
from ..service_models import CrewMembers, OwnCrew
from ..crew_optional_data import CrewOptionalSnapshot
from ..visual_library_bundle import decode_visual_unityfs
from ..tnr_visual_probe import _TNR_COMPARISON_LIBRARIES

_CURRENT_BRANCH = '6_8_0_Release'  # release selected explicitly; not a global latest-branch oracle
_SOURCES = tuple(sorted({name for pair in _TNR_COMPARISON_LIBRARIES.values() for name in pair}))
_MAX_LOCAL_FIXTURE = 8 * 1024 * 1024


@dataclass(frozen=True)
class CurrentSourceEvidence:
    report: dict[str, Any]
    sources: GameVisualLibrary


def fetch_current_visual_ids(branch: str, *, session: Any) -> CurrentSourceEvidence:
    """2 index reads + exactly six source reads; public GET only, no redirects.

    The latest version is the *currently advertised database for this branch*.
    It is not proof that a different/newer release branch does not exist.
    """
    if type(branch) is not str or not _BRANCH.fullmatch(branch):
        raise ValueError('invalid explicitly selected release branch')
    if DEFAULT_BASE_URL.rstrip('/') != _CDN_ORIGIN:
        raise PublicCDNProbeError('unexpected CDN origin')
    count = 0

    def get(url: str, max_bytes: int) -> bytes:
        nonlocal count
        if count >= 2 + len(_SOURCES):
            raise PublicCDNProbeError('request budget exceeded')
        count += 1
        return _bounded_get(session, url, max_bytes)

    version = _json(get(f'{_CDN_ORIGIN}/asset_database_{branch}.version', _MAX_VERSION_BYTES))
    if not isinstance(version, dict):
        raise PublicCDNProbeError('unsupported version response')
    database_version = str(version.get('version', ''))
    if not _VERSION.fullmatch(database_version):
        raise PublicCDNProbeError('invalid database version')
    raw_index = get(f'{_CDN_ORIGIN}/asset_database.{database_version}.json', _MAX_DATABASE_BYTES)
    try:
        db = AssetDatabase.from_json(_json(raw_index))
    except (TypeError, ValueError, KeyError, AttributeError) as exc:
        raise PublicCDNProbeError('invalid database index') from exc
    if str(db.version) != database_version:
        raise PublicCDNProbeError('database index/version mismatch')

    all_records: list[VisualCodeName] = []
    counts: dict[str, int] = {}
    digests: dict[str, str] = {}
    versions: dict[str, str] = {}
    planned_assets: list[tuple[str, str, int]] = []
    # Validate *all* source addresses/sizes before downloading any bundle.
    for name in _SOURCES:
        asset = db.assets.get(name)
        if asset is None:
            raise PublicCDNProbeError('a required cosmetic library is not indexed')
        asset_version = str(asset.version)
        size = asset.size('ASTC')
        if not _VERSION.fullmatch(asset_version) or type(size) is not int or not 64 <= size <= _MAX_ASSET_BYTES:
            raise PublicCDNProbeError('invalid source version or size')
        planned_assets.append((name, asset_version, size))
    for name, asset_version, size in planned_assets:
        url = f'{_CDN_ORIGIN}/ANDROID/ASTC/{name}.ASTC.{asset_version}'
        raw = get(url, min(size + 1, _MAX_ASSET_BYTES))
        if len(raw) != size:
            raise PublicCDNProbeError('source size differs from database')
        try:
            decoded = decode_visual_unityfs(raw, library=name)
        except (ValueError, TypeError, IndexError) as exc:
            raise PublicCDNProbeError('cosmetic source failed native validation') from exc
        counts[name] = len(decoded.records)
        digests[name] = hashlib.sha256(raw).hexdigest()
        versions[name] = asset_version
        all_records.extend(decoded.records)
    return CurrentSourceEvidence(
        report={
            'status': 'current_release_public_cosmetic_sources_validated',
            'branch': branch,
            'database_version': database_version,
            'database_version_is_current_for_selected_branch_only': True,
            'index_sha256': hashlib.sha256(raw_index).hexdigest(),
            'source_sha256': digests,
            'source_versions': versions,
            'source_record_counts': counts,
            'source_total_records': sum(counts.values()),
            'network_requests': count,
            'max_network_requests': 2 + len(_SOURCES),
            'authentication_used': False,
            'gameplay_read_count': 0,
            'roster_unresolved_ids_identifiable_from_public_sources_alone': False,
            'roster_unresolved_ids_status': 'saved_roster_fixtures_required',
            'mapping_acceptance_or_visual_verification': False,
        },
        sources=GameVisualLibrary(tuple(all_records)),
    )


def catalog_ids_one_by_one(evidence: CurrentSourceEvidence) -> dict[str, Any]:
    """Opt-in listing of *public source IDs*, not unresolved roster IDs."""
    names = set(_SOURCES)
    if set(evidence.report.get('source_record_counts', {})) != names:
        raise ValueError('six validated sources are required')
    items = [
        {
            'slot': r.slot, 'numeric_id': r.code,
            'source_library': r.source_library,
            'source_label': r.name,
            'additional_source_labels': list(r.names[1:]),
            'source_category': 'All' if r.model_key == '*' else r.model_key,
            'vehicle_eligibility_verified': False,
            'unresolved_roster_id': 'unknown_without_saved_roster',
        }
        for r in evidence.sources.records
        if r.source_library in names and type(r.code) is int
    ]
    items.sort(key=lambda r: (r['slot'], r['numeric_id'], r['source_library']))
    return {
        'status': 'public_source_id_catalog_not_unresolved_roster_ids',
        'branch': evidence.report['branch'],
        'database_version': evidence.report['database_version'],
        'source_sha256': evidence.report['source_sha256'],
        'individual_source_ids': items,
        'contains_player_or_roster_data': False,
        'source_label_is_visually_verified': False,
        'mapping_promoted': False,
    }


def unmatched_ids_one_by_one(own_response: Any, members_response: Any,
                              sources: GameVisualLibrary, *,
                              branch: str, database_version: str) -> dict[str, Any]:
    """Only saved local, properly parsed crew fixtures; no service I/O.

    Enumerate each *distinct numeric ID* by field and TNR syntax cohort.
    A repeated ID produces one row with occurrences, not player-level rows.
    """
    own = OwnCrew.from_response(own_response)
    members = CrewMembers.from_response(own.crew_uid, members_response)
    snapshot = CrewOptionalSnapshot.from_reads(own, members)
    gaps = diagnose_paint_interior_gaps(snapshot, sources, show_numeric_ids=True)
    rows = []
    nonnumeric_count = 0
    for slot, cohorts in gaps['by_slot_and_cohort'].items():
        for cohort, stats in cohorts.items():
            nonnumeric_count += stats['unresolved_nonnumeric']
            for item in stats['numeric_ids']:
                rows.append({'slot': slot, 'cohort': cohort, 'numeric_id': item['id'],
                             'occurrences': item['occurrences'], 'reason': item['reason'],
                             'label': None, 'verified_visual_mapping': False})
    rows.sort(key=lambda r: (r['slot'], r['cohort'], r['numeric_id'], r['reason']))
    return {
        'status': 'saved_roster_unresolved_numeric_ids_current_sources',
        'branch': branch,
        'database_version': database_version,
        'snapshot_is_historical_dev24': False,
        'source_snapshot_member_count': gaps['source_snapshot_members'],
        'individual_unresolved_numeric_ids': rows,
        'unresolved_numeric_occurrences': sum(r['occurrences'] for r in rows),
        'unresolved_nonnumeric_occurrences': nonnumeric_count,
        'player_names_or_ids_included': False,
        'model_keys_or_wheel_strings_included': False,
        'gameplay_read_count': 0,
        'mapping_promoted': False,
    }


def _load_local_fixture(path: Path) -> Any:
    if path.is_symlink() or not path.is_file() or not 2 <= path.stat().st_size <= _MAX_LOCAL_FIXTURE:
        raise ValueError('invalid saved fixture')
    return json.loads(path.read_bytes().decode('utf-8-sig'))


def _write_private_new(path: Path, document: dict[str, Any]) -> None:
    """Fail closed; never overwrite; owner-only on POSIX."""
    if path.is_symlink() or path.exists() or not path.parent.is_dir():
        raise ValueError('output already exists or parent is unavailable')
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(document, f, indent=2, ensure_ascii=False)
            f.write('\n')
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description='Dev36 read-only current-branch public cosmetic IDs; no gameplay requests')
    parser.add_argument('--online', action='store_true', help='allow exactly eight public CDN GETs; default dry run')
    parser.add_argument('--branch', default=_CURRENT_BRANCH, help='explicit version branch (6_8_0_Release as of Oct 2026); no global discovery')
    parser.add_argument('--output', type=Path, help='NEW summary JSON with source counts/hashes, not IDs')
    parser.add_argument('--source-ids-output', type=Path, help='NEW PRIVATE JSON listing each public source ID and label')
    parser.add_argument('--own-json', type=Path, help='optional previously saved own crew response; use with --members-json')
    parser.add_argument('--members-json', type=Path, help='optional previously saved crew members response; use with --own-json')
    parser.add_argument('--unresolved-ids-output', type=Path, help='NEW PRIVATE list of unmatched numeric paint/interior roster IDs (requires both saved JSON fixtures)')
    args = parser.parse_args(argv)
    if type(args.branch) is not str or not _BRANCH.fullmatch(args.branch):
        parser.error('invalid release branch')
    if bool(args.own_json) != bool(args.members_json):
        parser.error('own and members fixtures must be supplied together')
    if args.unresolved_ids_output and not args.own_json:
        parser.error('unresolved IDs require already-saved roster fixtures')
    paths = [x for x in (args.output, args.source_ids_output, args.unresolved_ids_output) if x is not None]
    if len(set(paths)) != len(paths) or any(x.exists() or x.is_symlink() or not x.parent.is_dir() for x in paths):
        parser.error('every output must be a distinct new path with existing parent')
    if not args.online:
        print(json.dumps({'status': 'dry_run_no_network', 'selected_release': args.branch,
                          'planned_public_gets': 2 + len(_SOURCES), 'gameplay_read_count': 0,
                          'unresolved_roster_ids_require_saved_fixtures': True}, indent=2))
        return 0
    try:
        import requests
        with requests.Session() as session:
            session.trust_env = False  # no netrc, cookies, proxy auth
            evidence = fetch_current_visual_ids(args.branch, session=session)
        individual_catalog = catalog_ids_one_by_one(evidence) if args.source_ids_output else None
        unmatched = None
        if args.own_json is not None:
            unmatched = unmatched_ids_one_by_one(_load_local_fixture(args.own_json),
                _load_local_fixture(args.members_json), evidence.sources,
                branch=args.branch, database_version=evidence.report['database_version'])
            evidence.report['roster_unresolved_ids_status'] = 'computed_from_supplied_saved_roster'
            evidence.report['roster_unresolved_numeric_occurrences'] = unmatched['unresolved_numeric_occurrences']
            evidence.report['roster_unresolved_nonnumeric_occurrences'] = unmatched['unresolved_nonnumeric_occurrences']
        if args.output:
            _write_private_new(args.output, evidence.report)
        if args.source_ids_output:
            _write_private_new(args.source_ids_output, individual_catalog)
        if args.unresolved_ids_output:
            _write_private_new(args.unresolved_ids_output, unmatched)
        print(json.dumps(evidence.report, indent=2))
        return 0
    except (Exception, KeyboardInterrupt):
        # Credentials, source labels, local fixture data/paths never enter errors.
        print(json.dumps({'status': 'public_cosmetic_id_test_unavailable',
                          'data_not_published': True, 'mapping_promoted': False}))
        return 3


if __name__ == '__main__':
    raise SystemExit(main())
