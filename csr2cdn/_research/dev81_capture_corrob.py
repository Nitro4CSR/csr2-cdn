"""Dev81: compare multiple signed Dev78/79 capture bundles offline.

This checks signed-file integrity, anti-duplicate conditions and logical agreement
between submitted snapshots. Neither signer independence nor real gameplay is
established by the data. Never promote an observed or synthetic paint mapping.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, NamedTuple

from .dev77_gacha_config_validity import inspect as inspect_dev77
from .dev79_capture_provenance import read_bounded_json, sha256_file, validate_manifest
from .dev80_capture_attestation import read_exact_regular_file, verify_attestation

_MAX_BUNDLES = 8


class CaptureBundle(NamedTuple):
    snapshot: Path
    manifest: Path
    public_key: Path
    signature: Path
    trusted_key_sha256: str
    challenge: str


def _bundle(bundle: CaptureBundle, apk_sha256: str) -> dict[str, Any]:
    """Validate each raw input only once; keep private payload out of reports."""
    snapshot, raw_snapshot = read_bounded_json(bundle.snapshot)
    manifest, raw_manifest = read_bounded_json(bundle.manifest)
    stage = validate_manifest(snapshot, raw_snapshot, manifest, apk_sha256)
    key = read_exact_regular_file(bundle.public_key, 32)
    sig = read_exact_regular_file(bundle.signature, 64)
    attestation = verify_attestation(raw_manifest, key, sig, bundle.challenge,
                                     bundle.trusted_key_sha256)
    # The attestation covers raw manifest; the manifest covers raw snapshot.
    assessment = stage['snapshot_assessment']
    lookup = assessment['paint_lookup_assessment']
    post = assessment['paint_post_refresh_assessment']
    gacha = assessment['gacha_assessment']
    fields = {
        'gacha_call_observed': gacha['reported_call_observed'] if gacha else None,
        'gacha_selected_config_index': gacha['selected_gacha_config_index'] if gacha else None,
        'gacha_predicted_gate': gacha['predicted_native_gate'] if gacha else None,
        'lookup_list_sha256': lookup['ordered_list_sha256'] if lookup else None,
        'lookup_selected_index': lookup['selected_index'] if lookup else None,
        'lookup_resolved_paint_id': lookup['resolved_paint_id'] if lookup else None,
        'lookup_observed_paint_id_matches': lookup['observed_id_matches_index'] if lookup else None,
        'post_list_sha256': post['ordered_list_sha256'] if post else None,
        'post_selected_index': post['selected_index'] if post else None,
        'post_resolved_paint_id': post['resolved_paint_id'] if post else None,
        'post_observed_paint_id_matches': post['observed_id_matches_index'] if post else None,
    }
    fully_observed = bool(gacha is not None and lookup is not None and post is not None and
        lookup['index_in_bounds'] and post['index_in_bounds'] and
        lookup['observed_id_supplied'] and post['observed_id_supplied'] and
        lookup['observed_id_matches_index'] is True and
        post['observed_id_matches_index'] is True)
    return {
        'capture_kind': stage['capture_kind'],
        'capture_label_sha256': stage['capture_label_sha256'],
        'raw_snapshot_sha256': hashlib.sha256(raw_snapshot).hexdigest(),
        'raw_manifest_sha256': attestation['raw_manifest_sha256'],
        'signer_public_key_sha256': attestation['public_key_sha256'],
        'challenge_sha256': attestation['verifier_challenge_sha256'],
        'ed25519_signature_valid': attestation['detached_signature_valid'],
        'native_stage_markers_valid': stage['native_rva_stage_anchors_match_pinned_locations'],
        'observations_complete': fully_observed,
        'per_capture_list_and_index_stable': (
            assessment['ordered_list_unchanged_after_refresh'] is True and
            assessment['selected_index_unchanged_after_refresh'] is True and
            assessment['resolved_id_unchanged_after_refresh'] is True),
        'comparison_fields': fields,
    }


def compare_signed_bundles(apk_sha256: str, bundles: list[CaptureBundle]) -> dict[str, Any]:
    """Purely offline correlation. Out-of-band operator independence is unknown."""
    if not 2 <= len(bundles) <= _MAX_BUNDLES:
        raise ValueError('Dev81 needs 2-8 complete capture bundles')
    reports = [_bundle(bundle, apk_sha256) for bundle in bundles]
    unique_fields = ('capture_label_sha256', 'raw_snapshot_sha256', 'raw_manifest_sha256',
                     'signer_public_key_sha256', 'challenge_sha256')
    for name in unique_fields:
        if len({report[name] for report in reports}) != len(reports):
            raise ValueError('captures reuse ' + name + '; independent-bundle claim rejected')
    checks = reports[0]['comparison_fields']
    disagreements = [name for name in checks if
                     any(report['comparison_fields'][name] != checks[name] for report in reports[1:])]
    all_complete = all(report['observations_complete'] for report in reports)
    all_stable = all(report['per_capture_list_and_index_stable'] for report in reports)
    kinds = [report['capture_kind'] for report in reports]
    passive_only = all(kind == 'passive_runtime' for kind in kinds)
    if disagreements:
        status = 'signed_submissions_disagree_no_runtime_conclusion'
    elif not all_complete or not all_stable:
        status = 'signed_submissions_incomplete_or_mutating_no_runtime_conclusion'
    elif not passive_only:
        status = 'synthetic_submissions_agree_not_runtime_evidence'
    else:
        status = 'self_reported_signed_submissions_agree_origin_not_authenticated'
    return {
        'status': status,
        'bundle_count': len(reports),
        'bundle_summaries': reports,
        'all_detached_signatures_valid': True,
        'separate_keys_challenges_and_raw_capture_files': True,
        'all_observation_stages_complete': all_complete,
        'all_per_capture_paint_states_stable': all_stable,
        'all_capture_kinds_claim_passive_runtime': passive_only,
        'between_bundle_disagreement_fields': disagreements,
        'between_bundle_observation_values_agree': not disagreements,
        'external_capture_origin_independently_authenticated': False,
        'independent_signer_control_established': False,
        'verifier_key_pins_or_challenges_independently_trusted': False,
        'non_mutating_gameplay_observation_independently_verified': False,
        'production_paint_mapping_verified': False,
        'production_mappings_changed': False,
        'limitation': 'Multiple signatures and matching file reports do not establish independent operators or genuine game execution.',
    }


def assess(apk: Path, bundles: list[CaptureBundle] | None = None) -> dict[str, Any]:
    bundles = [] if bundles is None else bundles
    if bundles and not 2 <= len(bundles) <= _MAX_BUNDLES:
        raise ValueError('Dev81 needs 2-8 complete capture bundles')
    apk_hash_before = sha256_file(apk)
    static = inspect_dev77(apk)
    if static['production_mappings_changed'] or static['runtime_ordered_paint_list_captured']:
        raise ValueError('pinned Dev77 native-only guard changed')
    corroboration = compare_signed_bundles(apk_hash_before, bundles) if bundles else None
    if sha256_file(apk) != apk_hash_before:
        raise ValueError('APK changed during offline validation')
    return {
        'status': 'dev81_offline_cross_bundle_corrob',
        'client': 'CSR2 6.8.0',
        'previous_dev72_77_pinned_native_chain_passed': True,
        'dev77_config_validity_native_sha256': static['native_method']['sha256'],
        'capture_bundles_supplied': len(bundles),
        'cross_bundle_assessment': corroboration,
        'missing_capture_artifacts': ['two_or_more_separately_attested_runtime_capture_bundles'] if not bundles else [],
        'conditional_index_15_paint_candidate': 1323,
        'paint_index_0_runtime_mapping_verified': False,
        'independent_runtime_origin_verified': False,
        'production_paint_mapping_verified': False,
        'production_mappings_changed': False,
        'network_requests': 0,
        'authenticated_gameplay_requests': 0,
        'gameplay_state_writes': 0,
        'private_capture_echoed_to_report': False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apk', type=Path, required=True)
    parser.add_argument('--capture', nargs=6, action='append', metavar=(
        'SNAPSHOT', 'MANIFEST', 'PUBLIC_KEY', 'SIGNATURE', 'TRUSTED_KEY_SHA256', 'CHALLENGE'),
        help='Repeat 2-8 times; each complete signed capture has six inputs')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output.exists() or args.output.is_symlink():
        parser.error('refusing to overwrite existing evidence output')
    try:
        captures = [CaptureBundle(*(Path(p) for p in row[:4]), *row[4:])
                    for row in (args.capture or [])]
        result = assess(args.apk, captures)
        body = json.dumps(result, sort_keys=True, indent=2, ensure_ascii=True) + '\n'
        if len(body.encode('utf-8')) > 175_000:
            raise ValueError('oversized evidence report')
        with args.output.open('x', encoding='utf-8') as stream:
            stream.write(body)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    print('Dev81: offline signed-bundle comparison complete; no production mapping promoted.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
