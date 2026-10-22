"""Dev27: source-only wheel metadata counts. No roster, CDN, or gameplay I/O.

This is a structural inventory of already-decoded original UnityFS fields,
NOT a resolver for roster wheel strings or an eligibility rule for a car.
The official decoder and production source-ID loader remain unchanged.
"""
from __future__ import annotations

from collections import Counter
import struct
from typing import Any

from ..database import AssetDatabase
from .dev31_rim_namespace import audit_rim_string_shapes
from .dev32_rim_topology import audit_rim_relationship_topology
from .dev33_rim_crossfield import audit_rim_crossfield_structure
from ..service_prestige_unityfs import load_unityfs
from ..visual_library_bundle import (
    VisualLibrarySourceError, _i32, _parse_records, _rim_trailer,
    _string_array, _u32, _unity_string, decode_visual_unityfs,
)


def _namespace_lexical_overlap(left: set[str], right: set[str]) -> dict[str, Any]:
    """Compare spelling families only; NEVER infer a shared identifier namespace.

    Exact, Unicode-casefolded, and punctuation-insensitive matches are counted
    separately. The last two are many-to-one transformations and can create
    false positives; no original names, IDs or mappings are emitted.
    """
    def case(s: str) -> str:
        return s.strip().casefold()

    def compact(s: str) -> str:
        return ''.join(char for char in s.casefold() if char.isalnum())

    l = {s for s in left if s}
    r = {s for s in right if s}
    lcase, rcase = {case(s) for s in l}, {case(s) for s in r}
    lcompact, rcompact = {compact(s) for s in l}, {compact(s) for s in r}
    lcompact.discard('')
    rcompact.discard('')
    return {
        'exact_shared_distinct_strings': len(l & r),
        'casefold_shared_normalized_keys': len(lcase & rcase),
        'punctuation_insensitive_shared_normalized_keys': len(lcompact & rcompact),
        'normalization_can_create_false_positives': True,
        'is_verified_name_join': False,
    }


def _audit_rim_rows(node: bytes, pos: int, expected: tuple, *,
                    private_fields: bool = False) -> dict[str, Any]:
    """Independently re-walk validated CarRims and root string arrays.

    Exposes counts only. Whole-record identity and a valid native rim trailer
    must agree with the canonical decoder, or the audit fails closed.
    """
    rim_names = set()
    private_rims: list[dict[str, Any]] = []
    references: list[str] = []
    compatible_rows: list[tuple[str, ...]] = []
    brands: list[str] = []
    categories: list[str] = []
    compatible_row_count = 0
    size_counts: Counter[int] = Counter()
    compatible_names: set[str] = set()
    rows_with_duplicate_compatible_names = 0
    compatible_empty_occurrences = 0
    duplicate_compatible_occurrences = 0
    for original in expected:
        ident = _i32(node, pos)
        name, pos = _unity_string(node, pos + 4)
        count = _u32(node, pos)
        if count > 64 or pos + 4 + 4 * count > len(node):
            raise VisualLibrarySourceError('invalid rim size array')
        size_counts[count] += 1
        pos += 4 + count * 4
        brand, pos = _unity_string(node, pos, empty=True)  # BrandName
        category, pos = _unity_string(node, pos, empty=True)  # Category
        compatible, pos = _string_array(node, pos, limit=1000)
        brands.append(brand)
        categories.append(category)
        compatible_rows.append(tuple(compatible))
        if (ident, name) != (original.code, original.name):
            raise VisualLibrarySourceError('rim audit disagrees with source decoder')
        rim_names.add(name)
        if private_fields:
            private_rims.append({
                'rim_source_id': ident,
                'rim_source_name': name,
                'brand_name': brand,
                'category': category,
                'compatible_cars': list(compatible),
                'available_size_entry_count': count,
            })
        compatible_row_count += bool(compatible)
        references.extend(compatible)
        compatible_names.update(compatible)
        if len(set(compatible)) < len(compatible):
            rows_with_duplicate_compatible_names += 1
        duplicate_compatible_occurrences += len(compatible) - len(set(compatible))
        compatible_empty_occurrences += compatible.count('')
    car_names, pos = _string_array(node, pos, limit=1000)
    defaults, pos = _string_array(node, pos, limit=1000)
    if len(node) - pos > 128:
        raise VisualLibrarySourceError('unverified rim trailer length')
    root_names = set(car_names)
    root_defaults = set(defaults)
    nonempty_compat = {name for name in compatible_names if name}
    nonempty_root = {name for name in root_names if name}
    result = {
        'status': 'native_rim_metadata_counts_not_roster_join',
        'rim_primary_records': len(expected),
        'rim_rows_with_explicit_compatible_cars': compatible_row_count,
        'rim_rows_without_explicit_compatible_cars': len(expected) - compatible_row_count,
        'compatible_car_string_occurrences': len(references),
        'distinct_compatible_car_strings': len(set(references)),
        'compatibility_strings_coinciding_with_root_car_names': sum(s in root_names for s in references),
        'compatible_car_empty_string_occurrences': compatible_empty_occurrences,
        'compatible_car_duplicate_string_occurrences_within_rows': duplicate_compatible_occurrences,
        'rim_rows_with_duplicate_compatible_cars': rows_with_duplicate_compatible_names,
        'distinct_nonempty_compatible_names_absent_from_root_car_names': len(nonempty_compat - nonempty_root),
        'distinct_nonempty_root_car_names_without_compatible_rim_reference': len(nonempty_root - nonempty_compat),
        'available_size_entry_counts_per_rim': {str(k): v for k, v in sorted(size_counts.items())},
        'root_car_names_count': len(car_names),
        'root_car_names_distinct_count': len(root_names),
        'root_defaults_distinct_count': len(root_defaults),
        'root_name_count_minus_defaults_count': len(car_names) - len(defaults),
        'distinct_root_name_count_equals_default_entry_count': len(root_names) == len(defaults),
        'equal_counts_do_not_establish_positional_pairing': True,
        'root_default_rim_strings_count': len(defaults),
        'root_name_default_count_equal': len(car_names) == len(defaults),
        'root_car_names_blank_entries': car_names.count(''),
        'root_car_names_duplicate_entries': len(car_names) - len(root_names),
        'root_default_rim_blank_entries': defaults.count(''),
        'root_default_rim_distinct_unrecognized_names': len({name for name in root_defaults if name and name not in rim_names}),
        'root_positional_pairing_is_eligibility': False,
        'root_default_strings_matching_primary_rim_names': sum(s in rim_names for s in defaults),
        'uninterpreted_trailing_bytes': len(node) - pos,
        'source_relationship_topology': audit_rim_relationship_topology(
            compatible_rows, car_names, defaults),
        'source_crossfield_relationships': audit_rim_crossfield_structure(
            compatible_rows, brands, categories),
        'supplementary_rim_field_shapes': {
            'brand_name': audit_rim_string_shapes(brands),
            'category': audit_rim_string_shapes(categories),
            'brand_category_pairs_distinct': len(set(zip(brands, categories))),
            'brand_category_not_vehicle_eligibility': True,
        },
        'namespace_string_shape_profiles': {
            'compatible_cars': audit_rim_string_shapes(references),
            'root_car_names': audit_rim_string_shapes(car_names),
            'root_default_rims': audit_rim_string_shapes(defaults),
        },
        'string_shape_does_not_establish_identifier_namespace': True,
        'lexical_namespace_overlap': {
            'compatible_cars_vs_root_car_names': _namespace_lexical_overlap(
                compatible_names, root_names),
            'root_default_rims_vs_primary_rim_names': _namespace_lexical_overlap(
                root_defaults, rim_names),
            'compatible_cars_vs_primary_rim_names': _namespace_lexical_overlap(
                compatible_names, rim_names),
        },
        'lexical_analysis_is_eligibility_or_roster_join': False,
        'compatible_cars_semantics_verified_for_roster': False,
        'root_car_name_to_default_rim_relationship_verified': False,
        'wheel_string_to_rim_name_join_verified': False,
        'identifiers_or_names_included': False,
        'network_requests': 0,
    }
    if private_fields:
        result['private_source_fields'] = {
            'status': 'opt_in_local_original_public_rim_fields_not_roster_mapping',
            'primary_rims': private_rims,
            'root_car_names': list(car_names),
            'root_default_rims': list(defaults),
            'root_arrays_are_not_positionally_paired': True,
            'compatible_cars_are_not_verified_vehicle_eligibility': True,
            'source_rim_ids_are_not_missing_roster_cosmetic_ids': True,
            'contains_original_source_names': True,
            'contains_player_or_roster_data': False,
        }
    return result


def audit_tuner_rim_source(raw: bytes, *, _private_fields: bool = False) -> dict[str, Any]:
    """Validate exact native rim library, then count compatibility metadata.

    The source is local, bounded by canonical decoder limits, and must admit
    exactly one array layout. By default, omit every source string.
    Private native fields are exposed only by an explicit local-only caller.
    """
    parsed = decode_visual_unityfs(raw, library='CarTunerStarsRimLibrary')
    _, _, _, nodes = load_unityfs(raw)
    node = nodes[0][1]
    data_offset = int.from_bytes(node[32:40], 'big')
    matches = []
    for pos in range(data_offset + 48, min(data_offset + 2048, len(node) - 32), 4):
        if _u32(node, pos) != len(parsed.records):
            continue
        try:
            source_rows, end = _parse_records(node, pos + 4, len(parsed.records), 'tuner_rim')
            if not _rim_trailer(node, end):
                continue
            if [(row[0], row[1]) for row in source_rows] != [
                    (r.code, r.name) for r in parsed.records]:
                continue
            matches.append(_audit_rim_rows(node, pos + 4, parsed.records,
                                           private_fields=_private_fields))
        except (VisualLibrarySourceError, UnicodeError, struct.error):
            continue
    if len(matches) != 1:
        raise VisualLibrarySourceError('unique independent native rim audit not available')
    return matches[0]


def extract_private_rim_source_fields(raw: bytes) -> dict[str, Any]:
    """Explicitly return original public rim strings for LOCAL inspection only.

    Never call from normal replay reports. This is not a roster join, trusted
    resolver, player-data export or a decoder for supplementary unknown fields.
    Uses the same unique native layout and canonical source validations as the
    counts-only audit, so data are never extracted from unvalidated bytes.
    """
    return audit_tuner_rim_source(raw, _private_fields=True)['private_source_fields']


def is_model_wheel_asset_code(asset_code: str, model: str) -> bool:
    """Require a whole '_Wheel' token; never accept Wheelbase/Wheels.

    A matching filename is candidate asset evidence only, not a roster join.
    """
    if type(asset_code) is not str or type(model) is not str or not 0 < len(model) <= 256:
        return False
    prefix = model + '_Wheel'
    return asset_code == prefix or (
        asset_code.startswith(prefix) and len(asset_code) > len(prefix)
        and asset_code[len(prefix)] in ('_', '.'))


def audit_wheel_asset_index(database: AssetDatabase) -> dict[str, Any]:
    """Summarize *possible* wheel-shaped asset codes without model disclosure.

    '_Wheel' is a lexical clue in the CDN index, NOT proof that this is a rim
    or matches the roster's separate wheel-name wire string. In particular,
    '_Wheelbase' must not count as a boundary-form wheel code.
    """
    if not isinstance(database, AssetDatabase):
        raise TypeError('AssetDatabase required')
    candidate_models: set[str] = set()
    exact = delimited = prefix_only = 0
    for asset in database.assets:
        name = asset.code
        if type(name) is not str or len(name) > 512:
            continue
        index = name.find('_Wheel')
        if index <= 0:
            continue
        end = index + len('_Wheel')
        if end == len(name):
            exact += 1
            candidate_models.add(name[:index])
        elif name[end] in ('_', '.'):
            delimited += 1
            candidate_models.add(name[:index])
        else:
            prefix_only += 1
    return {
        'status': 'wheel_asset_filename_pattern_candidates_only',
        'total_asset_entries': len(database.assets),
        'exact_wheel_suffix_candidates': exact,
        'delimited_wheel_suffix_candidates': delimited,
        'nondelimited_wheel_prefix_lookalikes': prefix_only,
        'distinct_candidate_model_prefixes': len(candidate_models),
        'asset_pattern_is_model_compatibility': False,
        'asset_pattern_is_roster_wheel_name_join': False,
        'asset_names_or_model_keys_included': False,
        'network_requests': 0,
    }
