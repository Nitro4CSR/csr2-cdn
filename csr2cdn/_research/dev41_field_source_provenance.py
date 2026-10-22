"""Dev41: strict offline evidence inventory, not a game-field schema decoder.

Derived from the actual observed crew wire projection, native decoder _SPECS,
and allowlisted NMG block names. Imported reports are sanitized aggregate
operator evidence; no account reads, CDN GETs or private source bundles.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Optional

from ..customization_evidence import CUSTOMIZATION_BLOCKS, SLOT_FIELDS
from ..crew_optional_data import CrewVehicleAppearance
from ..visual_library_bundle import _SPECS
from .dev36_latest_visual_ids import _write_private_new
from .dev37_source_id_lookup import _read_json

# Exact wire field names are from CrewVehicleAppearance.from_wire. No inferred
# field-to-asset join may be added as 'verified' merely because IDs coincide.
FIELD_CANDIDATES = {
    'car_paint_id': ('CarPaintLibrary', 'CarTunerStarsPaintLibrary'),
    'car_interior_id': ('CarInteriorLibrary', 'CarTunerStarsInteriorLibrary'),
    'car_calliper_id': ('CarCalliperLibrary', 'CarTunerStarsCalliperLibrary'),
    'car_livery_id': ('CarLiveryLibrary', 'CarTunerStarsLiveryLibrary'),
    'car_liveryZonesSet_id': ('LiveryZonesSetLibrary', 'TunerStarsLiveryZonesSetLibrary'),
    'car_wheel_name': ('CarTunerStarsRimLibrary',),
    'car_decal_flag_id': ('CarFlagLibrary',),
    'car_decal_number_id': ('CarRacingNumberLibrary',),
    'car_decal_numberplate_style_id': ('CarLicensePlateLibrary',),
    'car_decal_number_color_id': ('CarColorLibrary',),
    'car_decal_number_shape_color_id': ('CarColorLibrary',),
    'car_decal_number_zone_id': (),
    'car_decal_playername_state': (),
    'car_decal_crewname_state': (),
}
# Classification reflects only source review, not gameplay interpretation.
DIRECT_ID_CANDIDATES = frozenset((
    'car_paint_id', 'car_interior_id', 'car_calliper_id',
    'car_livery_id', 'car_liveryZonesSet_id',
    'car_decal_flag_id', 'car_decal_number_id',
    'car_decal_numberplate_style_id',
))
SLOT_BY_FIELD = {
    'car_paint_id': 'paint', 'car_interior_id': 'interior',
    'car_calliper_id': 'calliper', 'car_livery_id': 'livery',
    'car_liveryZonesSet_id': 'livery_zones_set',
    'car_wheel_name': 'wheel', 'car_decal_flag_id': 'decal_flag',
    'car_decal_number_id': 'decal_number',
    'car_decal_numberplate_style_id': 'decal_numberplate_style',
    'car_decal_number_color_id': 'decal_number_color',
    'car_decal_number_shape_color_id': 'decal_number_shape_color',
    'car_decal_number_zone_id': 'decal_number_zone',
}
_MAX_REPORT = 128 * 1024


def field_schema_inventory() -> list[dict[str, Any]]:
    """Provenance annotations, with all semantic verification flags false."""
    # Guard against an accidental stale copy of the known wire-field table.
    if set(FIELD_CANDIDATES) != {'car_' + k for k in (
        'paint_id', 'interior_id', 'calliper_id', 'livery_id',
        'liveryZonesSet_id', 'wheel_name', 'decal_flag_id',
        'decal_number_id', 'decal_numberplate_style_id',
        'decal_number_color_id', 'decal_number_shape_color_id',
        'decal_number_zone_id', 'decal_playername_state', 'decal_crewname_state',
    )}:
        raise ValueError('wire-field inventory is incomplete')
    expected_fields = set(SLOT_FIELDS.values())
    if not expected_fields.issubset(set(CrewVehicleAppearance.__dataclass_fields__)):
        raise ValueError('declared slot field is missing from wire projection')
    rows = []
    for wire_field, assets in FIELD_CANDIDATES.items():
        slot = SLOT_BY_FIELD.get(wire_field)
        candidates = []
        for asset in assets:
            spec = _SPECS.get(asset)
            candidates.append({
                'source_asset': asset,
                'native_decoder_supported': spec is not None,
                'native_primary_array': spec[1][0] if spec else None,
                'native_id_field': 'ID' if spec else None,
                'asset_exists_in_selected_database': None,  # no full index provided
                'same_namespace_demonstrated': False,
                'vehicle_eligibility_verified': False,
                'visual_appearance_verified': False,
            })
        rows.append({
            'wire_field': wire_field,
            'wire_type': 'string' if wire_field == 'car_wheel_name' else 'integer',
            'package_slot': slot,
            'relationship': ('numeric_id_candidate' if wire_field in DIRECT_ID_CANDIDATES
                             else 'unverified_possible_source' if assets else 'no_established_source'),
            'source_candidates': candidates,
            'explicit_native_field_join_found': False,
            'same_namespace_demonstrated': False,
            'vehicle_eligibility_verified': False,
            'visual_appearance_verified': False,
            'operator_display_alias': None,
        })
    return rows


def make_audit(*, source_summary: Optional[dict[str, Any]] = None,
               roster_report: Optional[dict[str, Any]] = None,
               palette_report: Optional[dict[str, Any]] = None,
               approve_transparent_zero: bool = False) -> dict[str, Any]:
    """Use reported aggregate observations without inventing metadata schemas."""
    fields = field_schema_inventory()
    reports = [x for x in (source_summary, roster_report, palette_report) if x is not None]
    if any(not isinstance(x, dict) for x in reports):
        raise ValueError('invalid report')
    if roster_report is not None and source_summary is None:
        raise ValueError('source summary required to contextualize roster coverage')
    if palette_report is not None and roster_report is None:
        raise ValueError('roster report required for palette comparison')
    db = branch = None
    hashes = None
    if source_summary is not None:
        if source_summary.get('status') != 'current_release_public_cosmetic_sources_validated':
            raise ValueError('unexpected source summary')
        db, branch = source_summary.get('database_version'), source_summary.get('branch')
        hashes = source_summary.get('source_sha256')
        if not (isinstance(db, str) and db.isdigit() and isinstance(branch, str)
                and isinstance(hashes, dict) and len(hashes) == 6):
            raise ValueError('invalid source version/fingerprints')
        for source in hashes:
            if source not in ('CarPaintLibrary','CarInteriorLibrary','CarCalliperLibrary',
                              'CarTunerStarsPaintLibrary','CarTunerStarsInteriorLibrary',
                              'CarTunerStarsCalliperLibrary'):
                raise ValueError('unexpected source')
        if any(not isinstance(x, str) or len(x) != 64 or
               any(c not in '0123456789abcdef' for c in x) for x in hashes.values()):
            raise ValueError('invalid source SHA')
        counts = source_summary.get('source_record_counts')
        if not isinstance(counts, dict) or set(counts) != set(hashes):
            raise ValueError('invalid source count keys')
        if any(type(n) is not int or n <= 0 for n in counts.values()):
            raise ValueError('invalid source record counts')
        for row in fields:
            for asset in row['source_candidates']:
                if asset['source_asset'] in counts:
                    asset['source_records_reported'] = counts[asset['source_asset']]
                    asset['source_report_sha256'] = hashes[asset['source_asset']]
                    asset['source_report_database_version'] = db
                    # The supplied six-source report establishes reported source
                    # presence, but not native field correspondence.
                    asset['asset_exists_in_selected_database'] = True
    id_coverage = {}
    unresolved = []
    if roster_report is not None:
        if (roster_report.get('status') != 'received_roster_numeric_ids_absent_from_source_libraries' or
            str(roster_report.get('source_database_version')) != db or
            roster_report.get('source_branch') != branch or
            roster_report.get('source_sha256') != hashes):
            raise ValueError('roster/source report mismatch')
        coverage = roster_report.get('coverage_by_attribute')
        if not isinstance(coverage, dict) or set(coverage) != {'paint','interior','calliper'}:
            raise ValueError('invalid roster coverage')
        for name, obj in coverage.items():
            if not isinstance(obj, dict):
                raise ValueError('invalid coverage')
            total = obj.get('received_numeric_occurrences')
            hits = obj.get('present_in_sources')
            misses = obj.get('absent_from_sources')
            unknown = obj.get('field_missing_or_unparsed')
            if any(type(v) is not int or v < 0 for v in (total,hits,misses,unknown)) or total != hits + misses:
                raise ValueError('contradictory coverage')
            id_coverage[name] = {'received':total, 'id_present_in_candidate_source':hits,
                                 'id_absent_from_candidate_sources':misses,
                                 'field_missing_or_unparsed':unknown,
                                 'same_namespace_demonstrated':False}
        unresolved = roster_report.get('individual_absent_received_ids')
        if not isinstance(unresolved, list) or len(unresolved) > 128:
            raise ValueError('invalid absent ID list')
        checked = set()
        for item in unresolved:
            if not isinstance(item, dict):
                raise ValueError('invalid absent ID record')
            kind, ident, n = item.get('attribute'), item.get('received_numeric_id'), item.get('occurrences')
            if kind not in id_coverage or type(ident) is not int or ident < 0 or type(n) is not int or n <= 0 or (kind, ident) in checked:
                raise ValueError('invalid or duplicate absent ID')
            checked.add((kind, ident))
        if any(sum(i['occurrences'] for i in unresolved if i['attribute'] == key) != id_coverage[key]['id_absent_from_candidate_sources'] for key in id_coverage):
            raise ValueError('roster absent ID count mismatch')
        unresolved = [{'attribute':i['attribute'], 'received_numeric_id':i['received_numeric_id'],
                       'occurrences':i['occurrences'], 'roster_field_join_verified':False}
                      for i in sorted(unresolved, key=lambda x:(x['attribute'],x['received_numeric_id']))]
    palette = None
    if palette_report is not None:
        if (palette_report.get('status') != 'received_paint_id_vs_separate_color_palette_checked' or
            palette_report.get('palette_database_version') != db or
            palette_report.get('roster_source_database_version') != db or
            palette_report.get('palette_branch') != branch or
            palette_report.get('roster_source_branch') != branch or
            palette_report.get('paint_to_color_namespace_join_verified') is True):
            raise ValueError('palette/source version mismatch')
        if (palette_report.get('source_paint_library_absence_unchanged') is not True or
                palette_report.get('numeric_palette_overlap_is_not_paint_name_mapping') is not True or
                palette_report.get('same_database_version_as_roster_sources') is not True):
            raise ValueError('palette report does not preserve namespace separation')
        matches = palette_report.get('individual_unmatched_received_paint_ids')
        if not isinstance(matches, list) or len(matches) != len(unresolved):
            raise ValueError('invalid palette comparison')
        expected = {i['received_numeric_id']:i['occurrences'] for i in unresolved if i['attribute']=='paint'}
        seen = set()
        for item in matches:
            if not isinstance(item, dict):
                raise ValueError('invalid palette row')
            ident = item.get('received_paint_id')
            if (type(ident) is not int or ident in seen or ident not in expected or
                item.get('occurrences') != expected[ident] or
                item.get('paint_to_color_namespace_join_verified') is not False or
                type(item.get('present_in_color_palette')) is not bool):
                raise ValueError('palette ID or count differs from roster evidence')
            seen.add(ident)
        zero = next((i for i in matches if i.get('received_paint_id') == 0), None)
        palette = {'source_asset':'CarColorLibrary',
                   'id_zero_palette_name':zero.get('palette_name') if zero else None,
                   'paint_to_palette_same_namespace_demonstrated':False,
                   'id_fifteen_present_in_palette': next((i.get('present_in_color_palette')
                           for i in matches if i.get('received_paint_id') == 15), None)}
        if approve_transparent_zero:
            if (not zero or zero.get('palette_name') != 'Transparent' or
                zero.get('present_in_color_palette') is not True or
                zero.get('paint_to_color_namespace_join_verified') is not False):
                raise ValueError('Transparent operator alias requires matching palette evidence')
            next(f for f in fields if f['wire_field']=='car_paint_id')['operator_display_alias'] = {'received_id':0,'label':'Transparent','status':'operator_approved_not_native_join'}
    elif approve_transparent_zero:
        raise ValueError('palette comparison required for alias approval')
    return {
        'status':'dev41_field_to_source_provenance_research',
        'source_database_version':db, 'source_branch':branch,
        'native_decode_is_not_roster_namespace_proof':True,
        'paint_and_color_namespaces_not_equated':True,
        'all_eligibility_and_visual_semantics_unverified':True,
        'wire_fields':fields,
        'reported_roster_exact_id_coverage':id_coverage,
        'unmatched_received_ids':unresolved,
        'palette_comparison':palette,
        'unparsed_customization_metadata_blocks':list(CUSTOMIZATION_BLOCKS),
        'metadata_field_schema_decoded':False,
        'network_requests':0, 'gameplay_read_count':0,
        'production_mappings_modified':False,
    }


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description='Offline field↔source evidence audit: no source promotion, no game/CDN I/O')
    p.add_argument('--source-summary', type=Path)
    p.add_argument('--received-report', type=Path)
    p.add_argument('--palette-report', type=Path)
    p.add_argument('--approve-transparent-zero', action='store_true')
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args(argv)
    if a.output.exists() or a.output.is_symlink() or not a.output.parent.is_dir():
        p.error('output must be a new file in an existing directory')
    try:
        args = {name: _read_json(path, _MAX_REPORT) if path else None for name,path in (
            ('source_summary', a.source_summary),('roster_report',a.received_report),('palette_report',a.palette_report))}
        result = make_audit(**args, approve_transparent_zero=a.approve_transparent_zero)
        _write_private_new(a.output, result)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        p.error('invalid, incompatible or unsafe report input')
    print(json.dumps({'status':'created','output':'written','wire_fields':len(result['wire_fields']),
                      'network_requests':0,'gameplay_read_count':0}, sort_keys=True))
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
