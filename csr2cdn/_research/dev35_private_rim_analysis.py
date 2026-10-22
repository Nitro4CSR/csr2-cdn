"""Dev35: local-only, redacted structural analysis of the Dev34 PRIVATE rim export.

No CDN requests, account connections, roster reads, or mapping promotion. The
original source fields are handled in memory and never copied into reports.
A count match or numeric representation is NOT evidence of rim eligibility.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import re
from typing import Any, Optional

_EXPORT_STATUS = 'opt_in_local_original_public_rim_fields_not_roster_mapping'
_HEX_SHA = re.compile(r'[a-f0-9]{64}\Z')
_DECIMAL = re.compile(r'[+-]?[0-9]{1,11}\Z')
_HEX = re.compile(r'0[xX][a-fA-F0-9]{1,8}\Z')
_MAX_EXPORT_BYTES = 16 * 1024 * 1024
_MAX_REPORT_BYTES = 128 * 1024


def _bounded_json(path: Path, maximum: int) -> dict[str, Any]:
    path = Path(path)
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= maximum:
        raise ValueError('invalid local source report')
    data = json.loads(path.read_bytes().decode('utf-8'))
    if type(data) is not dict:
        raise ValueError('local report must be an object')
    return data


def _strings(value: Any, maximum: int) -> list[str]:
    if (type(value) is not list or len(value) > maximum or
            any(type(item) is not str or len(item) > 4096 for item in value)):
        raise ValueError('unexpected native string array')
    return value


def _numeric_source_reference(s: str) -> Optional[int]:
    # Interpret ONLY unambiguous decimal or explicitly prefixed hexadecimal
    # syntax. Never guess bare hex, bit patterns, hashes or encoded game IDs.
    if _DECIMAL.fullmatch(s):
        n = int(s, 10)
    elif _HEX.fullmatch(s):
        n = int(s, 16)
    else:
        return None
    return n if -(2**31) <= n < 2**31 else None


def _numeric_profile(values: set[str], known_ids: set[int]) -> dict[str, Any]:
    parsed = {s: _numeric_source_reference(s) for s in values if s}
    numeric_values = {s: value for s, value in parsed.items() if value is not None}
    return {
        'distinct_strings': len({s for s in values if s}),
        'unambiguous_decimal_or_0x_numeric_strings': len(numeric_values),
        'numeric_values_coinciding_with_source_rim_ids': sum(
            n in known_ids for n in numeric_values.values()),
        'numeric_equality_proves_wheel_or_vehicle_mapping': False,
    }


def audit_private_rim_export(export: dict[str, Any], *,
                             expected_sha256: Optional[str] = None) -> dict[str, Any]:
    """Build a counts-only report from the specific Dev34 native export schema.

    Do not expose source strings or IDs; never join distinct namespaces.
    Caller may supply a separately recorded replay hash to verify provenance.
    """
    if (type(export) is not dict or export.get('status') != _EXPORT_STATUS or
            export.get('root_arrays_are_not_positionally_paired') is not True or
            export.get('compatible_cars_are_not_verified_vehicle_eligibility') is not True or
            export.get('source_rim_ids_are_not_missing_roster_cosmetic_ids') is not True or
            export.get('contains_original_source_names') is not True or
            export.get('contains_player_or_roster_data') is not False):
        raise ValueError('not a valid Dev34 private source export')
    digest = export.get('source_sha256')
    if type(digest) is not str or not _HEX_SHA.fullmatch(digest):
        raise ValueError('missing source fingerprint')
    if expected_sha256 is not None and (type(expected_sha256) is not str or
                                        digest != expected_sha256):
        raise ValueError('source fingerprint differs from separately recorded replay')

    names = _strings(export.get('root_car_names'), 1000)
    defaults = _strings(export.get('root_default_rims'), 1000)
    rims = export.get('primary_rims')
    if type(rims) is not list or not 0 < len(rims) <= 10000:
        raise ValueError('invalid rim source record array')
    ids: list[int] = []
    rim_names: list[str] = []
    compatibles: set[str] = set()
    compatibility_occurrences = 0
    for rim in rims:
        if type(rim) is not dict or any(key not in rim for key in (
                'rim_source_id', 'rim_source_name', 'brand_name', 'category',
                'compatible_cars', 'available_size_entry_count')):
            raise ValueError('unexpected rim source record')
        ident = rim['rim_source_id']
        if type(ident) is not int or not -(2**31) <= ident < 2**31:
            raise ValueError('invalid rim source integer')
        for field in ('rim_source_name', 'brand_name', 'category'):
            if type(rim[field]) is not str or len(rim[field]) > 4096:
                raise ValueError('invalid rim source string')
        available_sizes = rim['available_size_entry_count']
        if type(available_sizes) is not int or not 0 <= available_sizes <= 64:
            raise ValueError('invalid rim size count')
        refs = _strings(rim['compatible_cars'], 1000)
        compatibility_occurrences += len(refs)
        if compatibility_occurrences > 50000:
            raise ValueError('too many rim source references')
        compatibles.update(refs)
        ids.append(ident)
        rim_names.append(rim['rim_source_name'])

    positions: dict[str, list[int]] = {}
    for i, name in enumerate(names):
        positions.setdefault(name, []).append(i)
    repeated = [pos for pos in positions.values() if len(pos) > 1]
    nonadjacent_repeated = sum(any(b != a + 1 for a, b in zip(pos, pos[1:]))
                               for pos in repeated)
    adjacent_equal_pairs = sum(a == b for a, b in zip(names, names[1:]))
    runs = len(names) - adjacent_equal_pairs
    distinct_name_count = len(positions)
    return {
        'status': 'private_rim_structural_hypotheses_redacted_no_roster_join',
        'source_sha256': digest,
        'source_fingerprint_compared_to_independent_replay': expected_sha256 is not None,
        'rim_records': len(rims),
        'distinct_rim_source_ids': len(set(ids)),
        'duplicate_rim_source_id_occurrences': len(ids) - len(set(ids)),
        'distinct_primary_rim_names': len(set(rim_names)),
        'duplicate_primary_rim_name_occurrences': len(rim_names) - len(set(rim_names)),
        'root_arrays': {
            'car_name_entries': len(names),
            'distinct_car_names': distinct_name_count,
            'duplicate_car_name_occurrences': len(names) - distinct_name_count,
            'car_names_repeated_in_multiple_nonadjacent_runs': nonadjacent_repeated,
            'adjacent_identical_car_name_pairs': adjacent_equal_pairs,
            'car_name_contiguous_run_count': runs,
            'default_rim_entries': len(defaults),
            'distinct_default_rim_strings': len(set(defaults)),
            'car_name_entries_minus_default_entries': len(names) - len(defaults),
            'distinct_car_name_count_equals_default_entry_count': distinct_name_count == len(defaults),
            'collapsing_only_adjacent_duplicates_yields_default_entry_count': runs == len(defaults),
            'all_duplicate_car_names_are_adjacent': nonadjacent_repeated == 0,
            'array_cardinality_cannot_prove_positional_correspondence': True,
        },
        'numeric_key_hypothesis': {
            'compatible_car_strings': _numeric_profile(compatibles, set(ids)),
            'root_car_name_strings': _numeric_profile(set(names), set(ids)),
            'root_default_rim_strings': _numeric_profile(set(defaults), set(ids)),
            'numeric_string_parsing_is_restricted_to_decimal_and_prefixed_hex': True,
        },
        'literal_name_overlap': {
            'root_defaults_matching_primary_rim_names': len(set(defaults) & set(rim_names)),
            'compatible_cars_matching_primary_rim_names': len(compatibles & set(rim_names)),
            'compatible_cars_matching_root_car_names': len(compatibles & set(names)),
            'equality_cannot_prove_eligibility_or_roster_join': True,
        },
        'source_strings_or_numeric_ids_exposed': False,
        'gameplay_read_count': 0,
        'network_requests': 0,
        'mappings_promoted': False,
        'positional_root_arrays_joined': False,
    }


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description='Dev35 offline PRIVATE rim export structural audit (redacted output)')
    parser.add_argument('--private-rim-fields', type=Path, required=True,
                        help='Dev34 private export file, kept local')
    parser.add_argument('--baseline-replay', type=Path,
                        help='optional existing Dev30+ offline replay report to check original source SHA-256')
    parser.add_argument('--output', type=Path, help='NEW redacted audit JSON file')
    args = parser.parse_args(argv)
    try:
        if args.output is not None and (args.output.is_symlink() or args.output.exists() or
                                        not args.output.parent.is_dir()):
            raise ValueError('output must be a new file')
        digest = None
        if args.baseline_replay is not None:
            baseline = _bounded_json(args.baseline_replay, _MAX_REPORT_BYTES)
            if baseline.get('status') != 'cached_public_sources_revalidated_offline':
                raise ValueError('baseline is not an offline source replay')
            digest = baseline.get('source_sha256', {}).get('rim')
            if type(digest) is not str or not _HEX_SHA.fullmatch(digest):
                raise ValueError('baseline lacks rim source fingerprint')
        report = audit_private_rim_export(_bounded_json(args.private_rim_fields, _MAX_EXPORT_BYTES),
                                          expected_sha256=digest)
        if args.output is not None:
            fd = os.open(args.output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as f:
                    json.dump(report, f, indent=2, sort_keys=True)
                    f.write('\n')
            except BaseException:
                args.output.unlink(missing_ok=True)
                raise
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    except (Exception, KeyboardInterrupt):
        # Do not print original source strings, identifiers or local paths.
        print(json.dumps({'status': 'source_analysis_unavailable',
                          'no_mappings_changed': True}))
        return 3


if __name__ == '__main__':
    raise SystemExit(main())
