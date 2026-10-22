"""Dev25 offline-only, evidence-gated visual source investigation.

This does not alter the proven Dev23 TNR decoder or promote candidate names.
Only operator-supplied local originals and (optionally) offline crew fixtures are
read. No CDN, authentication or gameplay network call is performed here.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re
from typing import Any, Iterable, Optional

from ..crew_optional_data import CrewOptionalSnapshot
from ..database import AssetDatabase
from ..game_labels import GameVisualLibrary
from ..service_models import CrewMembers, OwnCrew
from ..tnr_visual_probe import (_MAX_DATABASE, _MAX_LOCAL_JSON,
    _TNR_COMPARISON_LIBRARIES, is_tnr_model, assess_tnr_resolution_comparison)
from ..visual_gap_diagnostics import analyze_visual_gaps
from ..visual_library_bundle import (VisualLibrarySourceError, _i32,
    _parse_tnr_records, _u32, _unity_string, decode_visual_unityfs,
    load_visual_unityfs)
from ..service_prestige_unityfs import load_unityfs
from .dev27_native_wheel_forensics import (
    audit_tuner_rim_source, audit_wheel_asset_index, is_model_wheel_asset_code,
)
from .dev28_opaque_tnr_forensics import summarize_opaque_tnr_tail

_TNR_NAMES = frozenset(name[1] for name in _TNR_COMPARISON_LIBRARIES.values())
_REQUIRED = frozenset(n for pair in _TNR_COMPARISON_LIBRARIES.values() for n in pair)
_WHEEL_TOKEN = re.compile(r'[A-Za-z0-9_]+\Z', re.ASCII)


def load_visual_libraries_unityfs(paths: Iterable[str | Path]) -> GameVisualLibrary:
    """FORENSICS ONLY: merge individually validated libraries without losing
    evidence when a standard and its TNR counterpart share a numeric ID.

    The ordinary production loader deliberately rejects all cross-source ID
    duplicates. Keep that production safety check unchanged. This function is
    used exclusively by the source-scoped Dev25 comparison: callers MUST NOT
    use its combined catalog for general purpose ``match()`` name resolution,
    because ambiguous (slot, numeric ID) records may coexist here.

    Even in forensics, reject duplicate input libraries and every collision
    other than the *declared* standard/TNR source pair for that particular
    paint, interior or caliper slot. The native per-file decoder remains the
    authority for record validity and category scoping.
    """
    compatible_pairs = {
        (slot, frozenset(pair)) for slot, pair in _TNR_COMPARISON_LIBRARIES.items()
    }
    source_names: set[str] = set()
    by_id: dict[tuple[str, int | str], set[str]] = {}
    merged = []
    for path in paths:
        name = Path(path).name.split('.')[0]
        if name in source_names:
            raise VisualLibrarySourceError('duplicate original visual source input')
        source_names.add(name)
        parsed = load_visual_unityfs(path)
        for record in parsed.records:
            if record.source_library != name:
                raise VisualLibrarySourceError('source name does not match native asset')
            key = (record.slot, record.code)
            prior = by_id.setdefault(key, set())
            if prior and any((record.slot, frozenset((source, name))) not in compatible_pairs
                             for source in prior):
                raise VisualLibrarySourceError('unsupported duplicate source IDs')
            prior.add(name)
            merged.append(record)
    if not merged:
        raise VisualLibrarySourceError('no source visual libraries supplied')
    return GameVisualLibrary(tuple(merged))


def audit_comparison_source_catalog(library: GameVisualLibrary) -> dict[str, Any]:
    """Source-level counts only; collisions do not imply actual roster joins."""
    if not isinstance(library, GameVisualLibrary):
        raise TypeError('decoded visual source required')
    by_source = Counter(record.source_library for record in library.records)
    collision_counts: dict[str, int] = {}
    for slot, (standard, tnr) in _TNR_COMPARISON_LIBRARIES.items():
        standard_ids = {r.code for r in library.records
                        if r.slot == slot and r.source_library == standard}
        tuner_ids = {r.code for r in library.records
                     if r.slot == slot and r.source_library == tnr}
        if standard in by_source and tnr in by_source:
            collision_counts[slot] = len(standard_ids & tuner_ids)
    return {
        'status': 'source_catalog_counts_not_roster_mappings',
        'records_per_source': dict(sorted(by_source.items())),
        'standard_tnr_duplicate_ids_by_slot': collision_counts,
        'collision_ids_disclosed': False,
        'ambiguous_ids_cannot_be_promoted': True,
        'general_purpose_resolution_from_merged_catalog_safe': False,
        'source_catalog_has_cross_source_id_collisions': any(collision_counts.values()),
        'ui_appearance_verified': False,
    }


def _local_bytes(path: str | Path, low: int, high: int) -> bytes:
    p = Path(path)
    if not p.is_file() or not low <= p.stat().st_size <= high:
        raise ValueError('missing, empty or oversized offline input')
    return p.read_bytes()


def _parsed_include_to_car(node: bytes, pos: int, count: int, slot: str):
    """Second, *diagnostic* walk of a validated primary array, without labels.

    This retrieves an encoded integer, not its game-side meaning. The canonical
    source decoder remains byte-for-byte unchanged.
    """
    flags = Counter()
    category_flag_counts: dict[str, Counter[int]] = {
        "all": Counter(), "model_specific_tnr_syntax": Counter(),
        "model_specific_other_syntax": Counter(),
    }
    global_count = model_count = 0
    for _ in range(count):
        if slot == 'paint':
            _, pos = _unity_string(node, pos)
            pos += 12 + 14 * 4
        elif slot == 'interior':
            pos += 4
            _, pos = _unity_string(node, pos)
            _, pos = _unity_string(node, pos)
            pos += 32
            pos = (pos + 1 + 3) & ~3
            pos += 8
        elif slot == 'calliper':
            pos += 4
            _, pos = _unity_string(node, pos)
            pos += 16 + 8
        else:
            raise VisualLibrarySourceError('unsupported TNR audit slot')
        flag = _i32(node, pos)
        category, pos = _unity_string(node, pos + 4)
        flags[flag] += 1
        if category.strip() == 'All':
            global_count += 1
            category_flag_counts['all'][flag] += 1
        else:
            model_count += 1
            category_flag_counts[
                'model_specific_tnr_syntax' if is_tnr_model(category.strip())
                else 'model_specific_other_syntax'
            ][flag] += 1
    return flags, global_count, model_count, category_flag_counts, pos


def audit_tnr_eligibility_source(raw: bytes, *, library: str) -> dict[str, Any]:
    """Report *only* metadata established by fully validated source bytes.

    Unknown trailer semantics and IncludeToCar values prevent any trusted
    per-car eligibility decision. This is intentionally not an eligibility
    resolver, and does not emit source model keys, labels or roster data.
    """
    if library not in _TNR_NAMES:
        raise ValueError('only primary TNR paint/interior/calliper sources are auditable')
    parsed = decode_visual_unityfs(raw, library=library)  # canonical fail-closed validation
    _, _, _, nodes = load_unityfs(raw)
    node = nodes[0][1]
    data_offset = int.from_bytes(node[32:40], 'big')
    slot = next(k for k, pair in _TNR_COMPARISON_LIBRARIES.items() if pair[1] == library)
    candidates = []
    for pos in range(data_offset + 48, min(data_offset + 2048, len(node) - 64), 4):
        count = _u32(node, pos)
        if count != len(parsed.records):
            continue
        try:
            source_rows, end = _parse_tnr_records(node, pos + 4, count, slot)
        except (VisualLibrarySourceError, UnicodeError):
            continue
        if (len(source_rows) != count or not 0 <= len(node) - end <= 256 * 1024
                or any((a[0], a[3]) != (b.code, b.model_key)
                       for a, b in zip(source_rows, parsed.records))):
            continue
        flags, global_count, model_count, scoped_flags, second_end = _parsed_include_to_car(node, pos + 4, count, slot)
        if second_end != end:
            raise VisualLibrarySourceError('TNR independent primary array audit disagrees')
        candidates.append((flags, global_count, model_count, scoped_flags, end))
    if len(candidates) != 1:
        raise VisualLibrarySourceError('unique auditable TNR array unavailable')
    flags, global_count, model_count, scoped_flags, end = candidates[0]
    return {
        'source_library': library,
        'primary_records': len(parsed.records),
        'category_all_records': global_count,
        'category_model_specific_records': model_count,
        'include_to_car_integer_histogram': {str(n): flags[n] for n in sorted(flags)},
        'include_to_car_by_source_category_syntax': {
            category: {str(n): histogram[n] for n in sorted(histogram)}
            for category, histogram in scoped_flags.items()},
        'source_category_syntax_is_game_eligibility': False,
        'uninterpreted_post_primary_bytes': len(node) - end,
        'opaque_tail_structural_screen': summarize_opaque_tnr_tail(node[end:]),
        'primary_source_validation': 'passed',
        'include_to_car_semantics_verified': False,
        'supplementary_compatibility_rules_verified': False,
        'trusted_car_specific_eligibility': False,
        'ui_appearance_verified': False,
    }


def diagnose_paint_interior_gaps(snapshot: CrewOptionalSnapshot,
                                  library: GameVisualLibrary,
                                  *, show_numeric_ids: bool = False) -> dict[str, Any]:
    """Tightly scoped residual-ID report using the same six-source decision tree.

    Even with opt-in, never emit player identity, model strings, labels, wheel
    strings, other cosmetic IDs, or member-level rows. Counts are deduplicated
    within (slot, TNR syntax cohort, reason, numeric ID).
    """
    if type(show_numeric_ids) is not bool:
        raise TypeError('show_numeric_ids must be boolean')
    comparison = assess_tnr_resolution_comparison(snapshot, library)
    sources = {name: GameVisualLibrary(tuple(r for r in library.records if r.source_library == name))
               for name in _REQUIRED}
    counts: dict[str, dict[str, Counter[tuple[str, int]]]] = {
        slot: {cohort: Counter() for cohort in comparison['cohorts']}
        for slot in ('paint', 'interior')}
    for member in snapshot.members:
        car = member.vehicle
        cohort = 'tnr_model_syntax' if is_tnr_model(car.model_key) else 'other_or_unknown_model'
        for slot in counts:
            code = getattr(car.appearance, slot + '_id') if car.appearance else None
            if code is None:
                continue
            ordinary_name, tuner_name = _TNR_COMPARISON_LIBRARIES[slot]
            standard = sources[ordinary_name].match(car.model_key, slot, code)
            tuner = sources[tuner_name].match(car.model_key, slot, code)
            if standard is not None and tuner is not None:
                reason = 'ambiguous_cross_library'
            elif standard is not None or (tuner is not None and cohort == 'tnr_model_syntax'):
                continue
            elif tuner is not None:
                reason = 'tnr_hit_outside_syntax_cohort'
            else:
                reason = 'not_matched_in_six_sources'
            # Wire numeric IDs only, not booleans/string projections.
            if type(code) is int:
                counts[slot][cohort][(reason, code)] += 1
    out: dict[str, Any] = {
        'status': 'unresolved_numeric_source_id_candidates_only',
        'comparison_source_count': len(_REQUIRED),
        'numeric_id_disclosure_opt_in': show_numeric_ids,
        'source_snapshot_members': len(snapshot.members),
        'by_slot_and_cohort': {},
        'model_keys_or_player_ids_included': False,
        'non_paint_interior_ids_included': False,
    }
    for slot, cohorts in counts.items():
        out['by_slot_and_cohort'][slot] = {}
        for cohort, pairs in cohorts.items():
            expected = comparison['cohorts'][cohort]['slots'][slot]['still_unresolved']
            if sum(pairs.values()) > expected:
                raise ValueError('gap IDs inconsistent with six-source comparison')
            entry: dict[str, Any] = {'unresolved': expected,
                                     'unresolved_nonnumeric': expected - sum(pairs.values()),
                                     'distinct_numeric_ids': len({i for _, i in pairs})}
            reasons: Counter[str] = Counter()
            for (reason, _), occurrences in pairs.items():
                reasons[reason] += occurrences
            entry['reasons'] = dict(sorted(reasons.items()))
            if show_numeric_ids:
                entry['numeric_ids'] = [
                    {'id': identifier, 'reason': reason, 'occurrences': n}
                    for (reason, identifier), n in sorted(pairs.items(), key=lambda pair: (pair[0][0], pair[0][1]))]
            out['by_slot_and_cohort'][slot][cohort] = entry
    return out


def _wheel_encoding_bucket(code: Any) -> str:
    if type(code) is not str or not code:
        return 'absent_or_nonstring'
    if len(code) > 256:
        return 'oversized_other'
    if code.isascii() and code.isdecimal():
        return 'decimal_digits'
    if _WHEEL_TOKEN.fullmatch(code):
        return 'ascii_token_with_underscore' if '_' in code else 'ascii_alphanumeric_token'
    return 'other_string_encoding'


def _wheel_length_bucket(value: Any) -> str:
    if type(value) is not str or not value:
        return 'absent'
    size = len(value)
    if size <= 8:
        return '1-8'
    if size <= 16:
        return '9-16'
    if size <= 32:
        return '17-32'
    if size <= 64:
        return '33-64'
    if size <= 256:
        return '65-256'
    return '>256'


def assess_wheel_evidence(snapshot: CrewOptionalSnapshot, database: AssetDatabase,
                          library: GameVisualLibrary) -> dict[str, Any]:
    """Check model assets and wheel wire shape independently; never name-join.

    Comparisons are made in memory and immediately reduced to counts. Exact
    string coincidence is explicitly NOT sufficient to trust a mapping.
    """
    if not isinstance(snapshot, CrewOptionalSnapshot) or not isinstance(database, AssetDatabase) or not isinstance(library, GameVisualLibrary):
        raise TypeError('typed snapshot, database and visual source required')
    if len(snapshot.members) > 30:
        raise ValueError('crew roster exceeds 30')
    assets = {asset.code for asset in database.assets}
    rims = {record.name for record in library.records if record.slot == 'tuner_rim'}
    output: dict[str, Any] = {}
    for name in ('tnr_model_syntax', 'other_or_unknown_model'):
        output[name] = {
            'members': 0, 'wheel_codes_present': 0,
            'model_wheel_asset_found': 0, 'model_wheel_asset_missing': 0,
            'wire_encoding_shapes': {},
            'wire_code_length_buckets': {},
            'exact_asset_code_overlap_candidate_only': 0,
            'asset_suffix_overlap_candidate_only': 0,
            'tuner_rim_name_overlap_candidate_only': 0,
        }
    encoding: dict[str, Counter[str]] = {k: Counter() for k in output}
    lengths: dict[str, Counter[str]] = {k: Counter() for k in output}
    for member in snapshot.members:
        car = member.vehicle
        cohort = 'tnr_model_syntax' if is_tnr_model(car.model_key) else 'other_or_unknown_model'
        group = output[cohort]
        group['members'] += 1
        model = car.model_key
        # A wheel bundle is model-specific; no global wheel asset join.
        prefixes = (f'{model}_Wheel' if type(model) is str and 0 < len(model) <= 256 else None)
        matching = {a for a in assets if prefixes is not None and is_model_wheel_asset_code(a, model)}
        group['model_wheel_asset_found' if matching else 'model_wheel_asset_missing'] += 1
        wheel = car.appearance.wheel_name if car.appearance else None
        encoding[cohort][_wheel_encoding_bucket(wheel)] += 1
        lengths[cohort][_wheel_length_bucket(wheel)] += 1
        if type(wheel) is str and wheel:
            group['wheel_codes_present'] += 1
            if wheel in matching:
                group['exact_asset_code_overlap_candidate_only'] += 1
            if any(wheel == a[len(prefixes):].lstrip('_') for a in matching):
                group['asset_suffix_overlap_candidate_only'] += 1
            if wheel in rims:
                group['tuner_rim_name_overlap_candidate_only'] += 1
    for name, group in output.items():
        group['wire_encoding_shapes'] = dict(sorted(encoding[name].items()))
        group['wire_code_length_buckets'] = dict(sorted(lengths[name].items()))
    return {
        'status': 'wheel_assets_and_wire_shape_not_mappings',
        'cohorts': output,
        'model_wheel_asset_is_roster_mapping': False,
        'tuner_stars_rim_is_universal_dictionary': False,
        'wheel_strings_included': False,
        'network_requests': 0,
    }


def assess_color_evidence(snapshot: CrewOptionalSnapshot, library: GameVisualLibrary) -> dict[str, Any]:
    """Standalone palette coincidences cannot establish roster decal color joins."""
    gaps = analyze_visual_gaps(snapshot, library)
    slots = ('decal_number_color', 'decal_number_shape_color', 'decal_number_zone')
    return {
        'status': 'palette_overlap_experimental_only',
        'standalone_color_source_supplied': any(r.slot == 'color' for r in library.records),
        'slots': {s: {'present': gaps.slots[s].present,
                      'palette_id_overlap_candidate_only': gaps.slots[s].palette_id_overlap,
                      'trusted_name_mappings': 0} for s in slots},
        'roster_palette_relationship_verified': False,
        'network_requests': 0,
    }


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description='Dev25 offline-only visual forensics; NO gameplay requests')
    parser.add_argument('--visual-asset-bundle', action='append', default=[],
                        help='operator-supplied original ASTC visual source; repeat')
    parser.add_argument('--asset-database', help='locally saved asset database')
    parser.add_argument('--own-json', help='locally saved own-crew fixture; requires --members-json')
    parser.add_argument('--members-json', help='locally saved crew-members fixture; requires --own-json')
    parser.add_argument('--show-unmatched-paint-interior-ids', action='store_true',
                        help='explicitly disclose numeric unresolved paint/interior IDs only')
    parser.add_argument('--output', help='new path to write sanitized JSON (refuses overwrite)')
    args = parser.parse_args(argv)
    if bool(args.own_json) != bool(args.members_json):
        parser.error('both offline fixtures are required')
    if args.own_json and (not args.asset_database or not args.visual_asset_bundle):
        parser.error('offline replay needs database and six visual sources')
    if args.show_unmatched_paint_interior_ids and not args.own_json:
        parser.error('numeric gap diagnostics require offline fixture inputs')
    if args.output and (Path(args.output).exists() or not Path(args.output).parent.is_dir()):
        parser.error('output must be a new file with existing parent directory')
    report: dict[str, Any] = {
        'status': 'dev25_offline_source_investigation',
        'network_requests': 0,
        'gameplay_read_count': 0,
        'tnr_decoder_modified': False,
        'candidate_names_trusted': False,
        'wheel_mappings_accepted': False,
        'color_mappings_accepted': False,
        'privacy': {'player_names': False, 'player_ids': False, 'model_keys': False,
                    'wheel_strings': False, 'raw_responses': False,
                    'numeric_paint_interior_ids_opt_in': args.show_unmatched_paint_interior_ids},
    }
    try:
        # Validate every original asset before any optional report write.
        visual = load_visual_libraries_unityfs(args.visual_asset_bundle) if args.visual_asset_bundle else None
        audits = []
        for item in args.visual_asset_bundle:
            name = Path(item).name.split('.')[0]
            if name in _TNR_NAMES:
                audits.append(audit_tnr_eligibility_source(_local_bytes(item, 64, 8 * 1024 * 1024), library=name))
        report['tnr_eligibility_source_audits'] = sorted(audits, key=lambda item: item['source_library'])
        rim_inputs = [p for p in args.visual_asset_bundle
                      if Path(p).name.split('.')[0] == 'CarTunerStarsRimLibrary']
        if rim_inputs:
            if len(rim_inputs) != 1:
                raise ValueError('duplicate tuner rim inputs')
            report['tuner_rim_source_audit'] = audit_tuner_rim_source(
                _local_bytes(rim_inputs[0], 64, 8 * 1024 * 1024))
        if args.asset_database:
            report['wheel_asset_index_audit'] = audit_wheel_asset_index(
                AssetDatabase.loads(_local_bytes(args.asset_database, 128, _MAX_DATABASE)))
        if visual is not None:
            report['source_catalog'] = audit_comparison_source_catalog(visual)
        report['tnr_supplementary_eligibility_verified'] = False
        if args.own_json:
            if not _REQUIRED.issubset({r.source_library for r in visual.records}):
                raise ValueError('six original decoded standard and TNR sources required')
            own = OwnCrew.from_response(json.loads(_local_bytes(args.own_json, 2, _MAX_LOCAL_JSON).decode('utf-8-sig')))
            roster = CrewMembers.from_response(own.crew_uid,
                json.loads(_local_bytes(args.members_json, 2, _MAX_LOCAL_JSON).decode('utf-8-sig')))
            snapshot = CrewOptionalSnapshot.from_reads(own, roster)
            db = AssetDatabase.loads(_local_bytes(args.asset_database, 128, _MAX_DATABASE))
            report['comparison'] = assess_tnr_resolution_comparison(snapshot, visual)
            report['paint_interior_gaps'] = diagnose_paint_interior_gaps(snapshot, visual,
                show_numeric_ids=args.show_unmatched_paint_interior_ids)
            report['wheels'] = assess_wheel_evidence(snapshot, db, visual)
            report['colors'] = assess_color_evidence(snapshot, visual)
        elif args.visual_asset_bundle or args.asset_database:
            report['status'] = ('dev25_source_only_no_roster' if args.visual_asset_bundle
                                else 'dev27_local_asset_index_only_no_roster')
        else:
            report['status'] = 'dev25_dry_run_no_inputs'
            report['next_step'] = 'optional previously saved original ASTC sources or asset index; no roster required for source-only audits'
        if args.output:
            with Path(args.output).open('x', encoding='utf-8') as stream:
                json.dump(report, stream, indent=2)
        print(json.dumps(report, indent=2))
        return 0
    except (Exception, KeyboardInterrupt):
        # Don't expose exception text/path, raw payloads, auth or private IDs.
        print(json.dumps({'status': 'offline_source_investigation_unavailable',
                          'details': 'suppressed', 'network_requests': 0}))
        return 3


if __name__ == '__main__':
    raise SystemExit(main())
