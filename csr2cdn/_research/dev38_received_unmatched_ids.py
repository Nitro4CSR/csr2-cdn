"""Dev38: list received cosmetic IDs absent from both source libraries for their slot.

Unlike a public source-ID catalogue, this requires a typed own-crew/crew-member
snapshot. Two authorized read-only game service operations are optional, or
previously saved own/member JSON can be processed entirely offline.

No gameplay writes, no raw roster persistence, no player/model/wheel output.
The report is about source *membership*, not vehicle eligibility or visual truth.
"""
from __future__ import annotations

import argparse
from collections import Counter
import getpass
import json
import os
from pathlib import Path
import sys
from typing import Any, Callable, Optional

from ..crew_optional_data import CrewOptionalSnapshot
from .dev36_latest_visual_ids import (_CURRENT_BRANCH, _load_local_fixture,
    _write_private_new, catalog_ids_one_by_one, fetch_current_visual_ids)
from .dev37_source_id_lookup import load_catalog
from ..service_models import CrewMembers, OwnCrew
from ..services import CSR2Services
from ..tnr_visual_probe import is_tnr_model
from .dev29_public_cdn_forensics import _BRANCH

FIELDS = {'paint': 'paint_id', 'interior': 'interior_id', 'calliper': 'calliper_id'}
COHORTS = ('tnr_model_syntax', 'other_or_unknown_model')
MAX_MEMBERS = 30


def compare_received_to_library_ids(snapshot: CrewOptionalSnapshot,
                                     catalog_rows: list[dict[str, Any]],
                                     *, branch: str, database_version: str,
                                     source_hashes: dict[str, str],
                                     capture_mode: str = 'offline') -> dict[str, Any]:
    """Use exact attribute+number membership; never infer model eligibility.

    Each (slot, number) occurs once in the output, with separate cohort counts.
    Missing fields are reported as missing data, not unmatched IDs. The same
    number in a different slot is deliberately NOT a match.
    """
    if not isinstance(snapshot, CrewOptionalSnapshot) or not 1 <= len(snapshot.members) <= MAX_MEMBERS:
        raise ValueError('one to thirty typed members required')
    if not isinstance(catalog_rows, list) or not catalog_rows:
        raise ValueError('nonempty verified catalogue required')
    if not isinstance(source_hashes, dict) or len(source_hashes) != 6:
        raise ValueError('six sources required')
    if not isinstance(branch, str) or not _BRANCH.fullmatch(branch):
        raise ValueError('invalid branch')
    if not isinstance(database_version, str) or not database_version.isdecimal():
        raise ValueError('invalid database version')

    present = {slot: set() for slot in FIELDS}
    for row in catalog_rows:
        slot, num = row.get('slot'), row.get('numeric_id')
        if slot not in FIELDS or type(num) is not int or num < 0:
            raise ValueError('invalid catalogue entry')
        present[slot].add(num)
    per_slot = {slot: {'received_numeric_occurrences': 0, 'present_in_sources': 0,
                       'absent_from_sources': 0, 'field_missing_or_unparsed': 0}
                for slot in FIELDS}
    missing: dict[tuple[str, int], Counter[str]] = {}
    for member in snapshot.members:
        appearance = member.vehicle.appearance
        cohort = 'tnr_model_syntax' if is_tnr_model(member.vehicle.model_key) else 'other_or_unknown_model'
        for slot, field in FIELDS.items():
            number = getattr(appearance, field, None) if appearance else None
            stats = per_slot[slot]
            if type(number) is not int or number < 0:
                stats['field_missing_or_unparsed'] += 1
                continue
            stats['received_numeric_occurrences'] += 1
            if number in present[slot]:
                stats['present_in_sources'] += 1
            else:
                stats['absent_from_sources'] += 1
                missing.setdefault((slot, number), Counter())[cohort] += 1
    rows = [{
        'attribute': slot, 'received_numeric_id': number,
        'occurrences': sum(missing[(slot, number)].values()),
        'tnr_model_syntax_occurrences': missing[(slot, number)]['tnr_model_syntax'],
        'other_or_unknown_model_occurrences': missing[(slot, number)]['other_or_unknown_model'],
        'reason': 'absent_from_both_standard_and_TNR_source_libraries_for_this_attribute',
        'vehicle_eligibility_verified': False,
    } for slot, number in sorted(missing, key=lambda pair: (('paint','interior','calliper').index(pair[0]), pair[1]))]
    return {
        'status': 'received_roster_numeric_ids_absent_from_source_libraries',
        'source_branch': branch, 'source_database_version': database_version,
        'source_sha256': dict(sorted(source_hashes.items())),
        'capture_mode': capture_mode,
        'historical_dev24_roster_reproduced': False,
        'crew_member_rows': len(snapshot.members),
        'identities_distinct': snapshot.identity_complete,
        'roster_count_matches_own_crew': snapshot.roster_count_matches_own_crew,
        'coverage_by_attribute': per_slot,
        'individual_absent_received_ids': rows,
        'unique_attribute_id_pairs_absent': len(rows),
        'total_absent_received_occurrences': sum(r['occurrences'] for r in rows),
        'presence_in_libraries_does_not_verify_vehicle_eligibility': True,
        'source_names_or_player_identifiers_included': False,
        'raw_roster_saved': False,
        'mapping_promoted': False,
    }


def compare_from_responses(own_response: Any, members_response: Any,
                           catalog_rows: list[dict[str, Any]], meta: dict[str, Any],
                           *, capture_mode: str) -> dict[str, Any]:
    own = OwnCrew.from_response(own_response)
    if not own.crew_uid:
        raise ValueError('own crew unavailable')
    members = CrewMembers.from_response(own.crew_uid, members_response)
    snapshot = CrewOptionalSnapshot.from_reads(own, members)
    return compare_received_to_library_ids(snapshot, catalog_rows,
        branch=meta['branch'], database_version=meta['database_version'],
        source_hashes=meta['source_sha256'], capture_mode=capture_mode)


def _get_player_id() -> str:
    """Never accept identifiers as CLI args (would expose process lists/history)."""
    value = os.environ.get('CSR2_PLAYER_ID', '').strip()
    if not value and sys.stdin.isatty():
        value = getpass.getpass('Own CSR2 PlayerID (hidden): ').strip()
    if not value:
        raise ValueError('CSR2_PLAYER_ID secret or interactive secure prompt required')
    return value


def _load_sources(*, catalog: Optional[Path], summary: Optional[Path],
                  refresh_public: bool, branch: str,
                  source_fetch: Callable[..., Any]) -> tuple[dict[str, Any], list[dict[str, Any]], int]:
    if refresh_public:
        import requests
        with requests.Session() as session:
            session.trust_env = False
            evidence = source_fetch(branch, session=session)
        doc = catalog_ids_one_by_one(evidence)
        return ({'branch': evidence.report['branch'],
                 'database_version': evidence.report['database_version'],
                 'source_sha256': evidence.report['source_sha256']},
                doc['individual_source_ids'], evidence.report['network_requests'])
    if catalog is None or summary is None:
        raise ValueError('validated catalogue and summary required')
    meta, rows = load_catalog(catalog, summary)
    return meta, rows, 0


def main(argv: Optional[list[str]] = None, *, services_factory=CSR2Services,
         source_fetch=fetch_current_visual_ids) -> int:
    parser = argparse.ArgumentParser(description='Dev38: EXACT received numeric paint/interior/calliper IDs absent from sources (dry run by default)')
    source = parser.add_mutually_exclusive_group()
    source.add_argument('--refresh-public', action='store_true', help='read current database + six libraries from public CDN (max 8 GETs)')
    source.add_argument('--catalog', type=Path, help='previously exported Dev36 source-ID catalogue (also requires --summary)')
    parser.add_argument('--summary', type=Path, help='Dev36 summary paired with --catalog')
    parser.add_argument('--branch', default=_CURRENT_BRANCH, help='explicit CDN release branch; not latest-across-all-branches discovery')
    parser.add_argument('--execute', action='store_true', help='opt into two read-only authorized game service operations')
    parser.add_argument('--own-json', type=Path, help='saved own-crew response for zero-network replay')
    parser.add_argument('--members-json', type=Path, help='saved crew-members response for zero-network replay')
    parser.add_argument('--output', type=Path, help='NEW local file containing all absent received numeric IDs one by one')
    args = parser.parse_args(argv)
    if not _BRANCH.fullmatch(args.branch):
        parser.error('invalid selected branch')
    if args.refresh_public and args.summary:
        parser.error('--summary cannot be combined with --refresh-public')
    if bool(args.catalog) != bool(args.summary):
        parser.error('--catalog and --summary must be paired')
    if bool(args.own_json) != bool(args.members_json):
        parser.error('--own-json and --members-json must be paired')
    if args.execute and args.own_json:
        parser.error('choose live read or local saved responses, not both')
    if not args.execute and not args.own_json:
        print(json.dumps({'status': 'dry_run_zero_requests',
            'planned_public_gets_if_refresh': 8 if args.refresh_public else 0,
            'planned_game_service_read_operations_if_execute': 2,
            'authentication_can_require_additional_HTTP_requests': True,
            'source': 'live_selected_branch' if args.refresh_public else 'validated_local_catalogue',
            'output_created': False}, indent=2))
        return 0
    if not args.refresh_public and not args.catalog:
        parser.error('supply --refresh-public or --catalog plus --summary')
    if not args.output or args.output.exists() or args.output.is_symlink() or not args.output.parent.is_dir():
        parser.error('--output must be a new file in an existing directory')
    try:
        # Validate existing source files and live account access before any CDN GET.
        if args.execute:
            player_id = _get_player_id()
        if args.catalog:
            meta, rows, public_gets = _load_sources(catalog=args.catalog,
                summary=args.summary, refresh_public=False, branch=args.branch,
                source_fetch=source_fetch)
        else:
            meta, rows, public_gets = _load_sources(catalog=None, summary=None,
                refresh_public=True, branch=args.branch, source_fetch=source_fetch)
        if args.execute:
            # Only these two existing allowlisted read contracts are invoked.
            # The service implementation additionally performs portal authentication
            # and may retry once after HTTP 401; do NOT assert total HTTP count == 2.
            with services_factory(player_id, allow_network=True) as service:
                own_json = service._read(service.prepare_my_crew())
                own = OwnCrew.from_response(own_json)
                if not own.crew_uid:
                    raise ValueError('own crew unavailable')
                members_json = service._read(service.prepare_crew_members(own.crew_uid))
            game_reads = 2
        else:
            own_json = _load_local_fixture(args.own_json)
            members_json = _load_local_fixture(args.members_json)
            game_reads = 0
        result = compare_from_responses(own_json, members_json, rows, meta,
            capture_mode='authorized_two_read_current_roster' if args.execute else 'saved_roster_offline_replay')
        result['public_cdn_get_count'] = public_gets
        result['game_service_read_operations'] = game_reads
        result['auth_http_request_count'] = 'not_instrumented' if args.execute else 0
        _write_private_new(args.output, result)
        # Intentionally show exactly the unmatched numeric IDs, not raw roster.
        print(json.dumps({'status': result['status'],
            'source_database_version': result['source_database_version'],
            'crew_member_rows': result['crew_member_rows'],
            'total_absent_received_occurrences': result['total_absent_received_occurrences'],
            'individual_absent_received_ids': result['individual_absent_received_ids'],
            'private_output_saved': True, 'raw_roster_saved': False,
            'game_service_read_operations': game_reads,
            'public_cdn_get_count': public_gets}, indent=2))
        return 0
    except (Exception, KeyboardInterrupt):
        # Fail closed: never show a private request, response, player ID or traceback.
        print(json.dumps({'status': 'dev38_diagnostic_unavailable',
                          'details': 'suppressed', 'raw_roster_saved': False}))
        return 3


if __name__ == '__main__':
    raise SystemExit(main())
