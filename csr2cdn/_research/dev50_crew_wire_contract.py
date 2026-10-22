"""Dev50: offline IL2CPP evidence for crew cosmetic *wire key* vs paint-index semantics.

Do not mistake an APK string literal for a proven serializer call site. This
reports evidence separately: compiled literal spellings, managed crew model
property names, the independently verified SMP JSON integer witness, and
(optional) *redacted* operator-provided aggregate roster observations.

No credentials, game requests, production mapping changes or raw roster output.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct
from typing import Any
from zipfile import ZipFile

from .dev47_apk_paint_semantics import _MAGIC, _MAX_METADATA, _META_PATH, _section
from .dev48_native_paint_methods import _SO_PATH, _MAX_NATIVE
from .dev49_native_paint_json import analyze as smp_native_audit

_WIRE_LITERALS = (
    'car_paint_id', 'car_interior_id', 'car_calliper_id', 'car_wheel_name',
)
_TYPE = 'CrewMemberCarInfo'
_CREW_METHODS = (
    'get_CarPaintIndex', 'set_CarPaintIndex', 'SetPaint',
    'get_CarInteriorID', 'get_CarCalliperID',
    'GetCurrentPlayersCurrentCarCrewMemberCarInfo',
)
_MAX_REPORT = 256 * 1024


def _name(strings: bytes, index: int) -> str:
    if not 0 <= index < len(strings):
        raise ValueError('invalid IL2CPP name offset')
    end = strings.find(b'\0', index)
    if end < 0:
        raise ValueError('unterminated IL2CPP name')
    return strings[index:end].decode('utf-8', 'replace')


def compiled_contract(metadata: bytes) -> dict[str, Any]:
    """Validate exact IL2CPP literal-table entries and a bounded crew type table."""
    if (len(metadata) < 0xb0 or len(metadata) > _MAX_METADATA or
            struct.unpack_from('<II', metadata, 0) != (_MAGIC, 31)):
        raise ValueError('unsupported IL2CPP metadata; expected version 31')
    lit_off, lit_bytes = _section(metadata, 0x08, 8)
    raw_off, raw_size = _section(metadata, 0x10, 1)
    str_off, str_len = _section(metadata, 0x18, 1)
    type_off, type_len = _section(metadata, 0xa0, 0x58)
    method_off, method_len = _section(metadata, 0x30, 36)
    strings = metadata[str_off:str_off+str_len]
    wanted = {s.encode(): s for s in _WIRE_LITERALS}
    found: dict[str, list[int]] = {s: [] for s in _WIRE_LITERALS}
    for i in range(lit_bytes // 8):
        length, rel = struct.unpack_from('<II', metadata, lit_off + i*8)
        if length > raw_size or rel > raw_size-length:
            raise ValueError('invalid IL2CPP literal-table offset')
        lit = metadata[raw_off+rel:raw_off+rel+length]
        if lit in wanted:
            found[wanted[lit]].append(i)
    # A string literal name does NOT establish the method that references it.
    types = []
    for t in range(type_len // 0x58):
        pos = type_off + t * 0x58
        if _name(strings, struct.unpack_from('<I', metadata, pos)[0]) != _TYPE:
            continue
        first = struct.unpack_from('<I', metadata, pos+0x24)[0]
        count = struct.unpack_from('<H', metadata, pos+0x40)[0]
        if first > method_len//36 or count > method_len//36-first:
            raise ValueError('invalid crew managed method range')
        methods = [_name(strings, struct.unpack_from('<I', metadata, method_off+j*36)[0])
                   for j in range(first, first+count)]
        types.append(methods)
    if len(types) > 1:
        raise ValueError('ambiguous CrewMemberCarInfo managed type')
    methods = types[0] if types else []
    return {
        'exact_literal_table_matches': {k: len(v) for k, v in found.items()},
        'literal_table_indices': {k: v for k, v in found.items()},
        'all_required_wire_spellings_present_once': all(len(x) == 1 for x in found.values()),
        'crew_member_class_present': len(types) == 1,
        'crew_index_method_names_present': {k: k in methods for k in _CREW_METHODS},
        'crew_member_has_own_explicit_serialize_to_json': 'SerializeToJson' in methods,
        'crew_member_has_own_explicit_serialize_from_json': 'SerializeFromJson' in methods,
        'literal_call_site_in_crew_serializer_verified': False,
        'roster_field_is_paint_index_verified': False,
        'global_paint_id_15_mapping_verified': False,
    }


def aggregate_observations(report: dict[str, Any]) -> dict[str, Any]:
    """Reconcile previously redacted Dev38 evidence only; no roster read."""
    if (type(report) is not dict or
            report.get('status') != 'received_roster_numeric_ids_absent_from_source_libraries' or
            report.get('raw_roster_saved') is not False or
            type(report.get('coverage_by_attribute')) is not dict):
        raise ValueError('unsupported redacted Dev38 report')
    fields = report['coverage_by_attribute']
    paint = fields.get('paint')
    if type(paint) is not dict:
        raise ValueError('missing paint coverage evidence')
    numbers = (paint.get('received_numeric_occurrences'),
               paint.get('present_in_sources'), paint.get('absent_from_sources'))
    if any(type(n) is not int or n < 0 for n in numbers) or numbers[0] != numbers[1] + numbers[2]:
        raise ValueError('inconsistent aggregate paint coverage')
    items = report.get('individual_absent_received_ids')
    if type(items) is not list or len(items) > 1000:
        raise ValueError('unbounded or missing aggregate ID entries')
    out, seen = [], set()
    for row in items:
        if type(row) is not dict or row.get('attribute') != 'paint':
            continue
        value, uses = row.get('received_numeric_id'), row.get('occurrences')
        if type(value) is not int or type(uses) is not int or value < 0 or uses < 1 or value in seen:
            raise ValueError('invalid or duplicated unmatched paint aggregate')
        seen.add(value)
        out.append({'paint_value': value, 'occurrences': uses,
                    'current_library_id_absent': True,
                    'could_be_car_specific_index': 'unverified',
                    'could_be_default_or_sentinel': 'unverified'})
    if sum(row['occurrences'] for row in out) != numbers[2]:
        raise ValueError('unmatched paint counts disagree with received roster aggregate')
    return {
        'database_version': report.get('source_database_version'),
        'paint_received_occurrences': numbers[0],
        'paint_matching_library_id_occurrences': numbers[1],
        'paint_unmatched_occurrences': numbers[2],
        'unmatched_paint_values': sorted(out, key=lambda row: row['paint_value']),
        'private_model_identifiers_exported': False,
        'original_roster_rows_exported': False,
    }


def inspect_apk(apk: Path, received: Path | None = None) -> dict[str, Any]:
    with ZipFile(apk) as z:
        chunks = []
        for path, cap in ((_META_PATH, _MAX_METADATA), (_SO_PATH, _MAX_NATIVE)):
            info = z.getinfo(path)
            if not 64 <= info.file_size <= cap:
                raise ValueError('unsupported size of APK component')
            chunks.append(z.read(info))
    meta, native = chunks
    compiled = compiled_contract(meta)
    smp = smp_native_audit(meta, native)
    result = {
        'status': 'dev50_compiled_crew_wire_literals_and_smp_path_audit',
        'apk_metadata_sha256': hashlib.sha256(meta).hexdigest(),
        'apk_native_sha256': hashlib.sha256(native).hexdigest(),
        'compiled_wire_and_crew_model': compiled,
        'independent_smp_json_roundtrip_witness': smp['native_evidence'],
        'smp_json_method_is_crew_service_serializer_verified': False,
        'compiled_literals_define_roster_field_semantics_verified': False,
        'roster_car_paint_id_is_global_id_verified': False,
        'roster_car_paint_id_is_vehicle_paint_index_verified': False,
        'vehicle_specific_paint_id_lookup_done': False,
        'paint_zero_user_approved_display_label': 'Transparent',
        'paint_zero_native_semantics_verified': False,
        'production_mappings_changed': False,
        'network_requests': 0, 'gameplay_reads': 0,
    }
    if received is not None:
        if received.stat().st_size > _MAX_REPORT:
            raise ValueError('redacted received report exceeds size limit')
        result['previous_redacted_roster_evidence'] = aggregate_observations(
            json.loads(received.read_text(encoding='utf-8')))
    return result


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--apk', type=Path, required=True)
    p.add_argument('--received-report', type=Path, help='previously redacted Dev38 JSON (no raw roster)')
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args(argv)
    if a.output.exists() or a.output.is_symlink():
        p.error('output path exists; refusing overwrite')
    try:
        result = inspect_apk(a.apk, a.received_report)
        with a.output.open('x', encoding='utf-8') as stream:
            json.dump(result, stream, indent=2, ensure_ascii=False)
            stream.write('\n')
    except (OSError, ValueError, KeyError, struct.error, TypeError) as exc:
        p.error(f'APK wire-context inspection failed: {type(exc).__name__}: {exc}')
    print('Compiled wire-key literals and SMP paint path audited; crew-service join remains unverified')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
