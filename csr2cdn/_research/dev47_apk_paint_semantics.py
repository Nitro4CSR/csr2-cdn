"""Dev47: provenance-preserving offline APK paint representation audit.

Reads IL2CPP *metadata names* rather than claiming to decompile native method
bodies. Private roster cache input is optional and NEVER included in reports.
Does not infer a global paint ID from a wire paint index or vice versa.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import struct
from typing import Any
from zipfile import ZipFile

_MAGIC = 0xFAB11BAF
_META_PATH = 'assets/bin/Data/Managed/Metadata/global-metadata.dat'
_MEMBER_PATH = 'endpoint-cache/game/members.json'
_MAX_METADATA = 64 * 1024 * 1024
_MAX_ROSTER = 2 * 1024 * 1024

# Selected names are explicit compiled symbols, not inferred relationships.
_FIELDS = {
    'CrewMemberCarInfo': ('<CarPaintIndex>k__BackingField', '<CarInteriorID>k__BackingField', '<CarCalliperID>k__BackingField'),
    'SMPHostInfo': ('<AppliedPaintIndex>k__BackingField', '<AppliedInteriorID>k__BackingField', '<AppliedCalliperID>k__BackingField'),
    'PlayerInfo': ('_paintIndex', '_interiorID', '_calliperID'),
    'CarGarageInstance': ('AppliedPaintIndex', '_OriginalPaintIndex', 'AppliedInteriorID', 'AppliedCalliperID'),
    'CarVisuals': ('CarPaintIDs', 'current_paint_index', 'CarInteriorIDs', 'CarCalliperIDs'),
}
_METHODS = {
    'CrewMemberCarInfo': ('SetPaint', 'get_CarPaintIndex'),
    'SMPHostInfo': ('UpdatePaintIndex', 'get_AppliedPaintIndex'),
    'CarPaintLibrary': ('GetIDByIndex', 'GetIndexByID'),
    'CarTNRPaintLibrary': ('GetIDByIndex', 'GetIndexByID'),
    'CarVisuals': ('SetPaintIDAddIfNecessary', 'get_CurrentPaintIndex'),
    'ConfiguratorMenuScreen': ('ShouldShowDefaultPaintForCar',),
    'FtueDealershipCarsConfig': ('GetForceDefaultPaint',),
    'CarAftermarketCustomisationsManager': ('IncludeCustomisationDefaultsForCar',),
}


def _u32(data: bytes, offset: int) -> int:
    if offset < 0 or offset + 4 > len(data):
        raise ValueError('invalid IL2CPP metadata offsets')
    return struct.unpack_from('<I', data, offset)[0]


def _section(data: bytes, header_offset: int, stride: int) -> tuple[int, int]:
    start, size = struct.unpack_from('<II', data, header_offset)
    if size % stride or start > len(data) or size > len(data) - start:
        raise ValueError('invalid IL2CPP metadata section')
    return start, size


def analyze_metadata(data: bytes) -> dict[str, Any]:
    if len(data) < 0xb0 or len(data) > _MAX_METADATA or _u32(data, 0) != _MAGIC:
        raise ValueError('not a supported IL2CPP metadata file')
    version = _u32(data, 4)
    if version != 31:
        raise ValueError('unsupported IL2CPP metadata version')
    strings_off, strings_len = _section(data, 0x18, 1)
    fields_off, fields_len = _section(data, 0x60, 12)
    methods_off, methods_len = _section(data, 0x30, 36)
    types_off, types_len = _section(data, 0xa0, 0x58)
    params_off, params_len = _section(data, 0x58, 12)
    strings = data[strings_off: strings_off + strings_len]

    def name(offset: int) -> str:
        if offset >= len(strings):
            raise ValueError('invalid IL2CPP string reference')
        end = strings.find(b'\x00', offset)
        if end < 0:
            raise ValueError('unterminated IL2CPP string')
        return strings[offset:end].decode('utf-8', errors='replace')

    field_names = [name(_u32(data, fields_off + i * 12)) for i in range(fields_len // 12)]
    method_records = [struct.unpack_from('<9I', data, methods_off + i * 36)
                      for i in range(methods_len // 36)]
    rows = {}
    for i in range(types_len // 0x58):
        o = types_off + i * 0x58
        tname = name(_u32(data, o))
        if tname not in _FIELDS and tname not in _METHODS:
            continue
        field_start, method_start = struct.unpack_from('<II', data, o + 0x20)
        method_count = struct.unpack_from('<H', data, o + 0x40)[0]
        field_count = struct.unpack_from('<H', data, o + 0x42)[0]
        if (field_start > len(field_names) or field_count > len(field_names) - field_start
                or method_start > len(method_records) or method_count > len(method_records) - method_start):
            raise ValueError('invalid IL2CPP type member range')
        declared = set(field_names[field_start:field_start + field_count])
        fields = [f for f in _FIELDS.get(tname, ()) if f in declared]
        names = set()
        method_params = {}
        for m in method_records[method_start: method_start + method_count]:
            mname = name(m[0])
            if mname not in _METHODS.get(tname, ()):
                continue
            count = m[8] >> 16
            start = m[4]
            if count > 32 or (count and (start > params_len // 12 or count > params_len // 12 - start)):
                raise ValueError('invalid IL2CPP method parameter range')
            parameters = [name(_u32(data, params_off + (start + k) * 12)) for k in range(count)]
            names.add(mname)
            method_params[mname] = parameters
        rows[tname] = {
            'fields_present': fields,
            'fields_not_found': [x for x in _FIELDS.get(tname, ()) if x not in declared],
            'method_parameters': method_params,
            'methods_not_found': [x for x in _METHODS.get(tname, ()) if x not in names],
        }
    return {
        'metadata_version': version,
        'metadata_sha256': hashlib.sha256(data).hexdigest(),
        'class_evidence': rows,
        'field_names_establish_serialization': False,
        'native_method_bodies_decompiled': False,
        'wire_car_paint_id_is_index_verified': False,
        'paint_zero_native_meaning_verified': False,
        'paint_fifteen_native_meaning_verified': False,
    }


def inspect_apk(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError('APK is missing')
    with ZipFile(path) as apk:
        info = apk.getinfo(_META_PATH)
        if info.file_size > _MAX_METADATA or info.file_size < 0xb0:
            raise ValueError('APK metadata size is out of bounds')
        raw = apk.read(info)
        if len(raw) != info.file_size:
            raise ValueError('truncated APK metadata')
    result = analyze_metadata(raw)
    # APK fingerprint is useful for provenance; the APK is not repackaged.
    sha = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(1024 * 1024):
            sha.update(chunk)
    result['apk_sha256'] = sha.hexdigest()
    return result


def roster_aggregate(cache_path: Path, catalog_path: Path | None = None) -> dict[str, Any]:
    """Summarize only roster paint numbers; never serialize entries or identifiers."""
    with ZipFile(cache_path) as z:
        info = z.getinfo(_MEMBER_PATH)
        if info.file_size > _MAX_ROSTER:
            raise ValueError('private roster exceeds size limit')
        payload = json.loads(z.read(info))
    if type(payload) is not dict or type(payload.get('scores')) is not list:
        raise ValueError('unknown private roster shape')
    paints = [row.get('car_paint_id') for row in payload['scores'] if type(row) is dict]
    valid = [v for v in paints if type(v) is int and 0 <= v < 2**63]
    bins = Counter(
        'zero' if v == 0 else
        'fifteen' if v == 15 else
        'other_under_100' if v < 100 else
        '100_to_999999' if v < 1_000_000 else
        'million_plus' for v in valid
    )
    out = {
        'roster_rows': len(paints),
        'valid_numeric_paint_values': len(valid),
        'coarse_paint_value_bins': {b: bins[b] for b in (
            'zero', 'fifteen', 'other_under_100', '100_to_999999', 'million_plus')},
        'private_roster_values_exported': False,
        'model_names_exported': False,
    }
    if catalog_path is not None:
        c = json.loads(catalog_path.read_text(encoding='utf-8'))
        if type(c) is not dict or type(c.get('individual_source_ids')) is not list:
            raise ValueError('invalid source ID catalogue')
        ids = {r['numeric_id'] for r in c['individual_source_ids']
               if type(r) is dict and r.get('slot') == 'paint' and
               type(r.get('numeric_id')) is int}
        out['library_match_occurrences'] = sum(v in ids for v in valid)
        out['library_absent_occurrences'] = sum(v not in ids for v in valid)
        out['catalog_database_version'] = c.get('database_version')
    return out


def make_report(apk: Path, *, cache: Path | None = None,
                catalog: Path | None = None) -> dict[str, Any]:
    report = {'status': 'apk_compiled_names_and_optional_private_roster_aggregate_only',
              'apk': inspect_apk(apk),
              'received_paint_is_global_id_verified': False,
              'received_paint_is_car_specific_index_verified': False,
              'source_library_index_conversion_behavior_verified': False,
              'opaque_symbol_names_are_not_method_execution': True,
              'paint_zero_operator_display_alias': 'Transparent',
              'paint_zero_alias_is_native_game_semantics': False,
              'paint_fifteen_display_mapping': None,
              'trusted_mappings_changed': False,
              'network_requests': 0, 'gameplay_read_count': 0}
    if cache is not None:
        report['roster_paint_aggregate'] = roster_aggregate(cache, catalog)
    return report


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--apk', required=True, type=Path)
    p.add_argument('--private-cache-zip', type=Path, help='optional local endpoint cache, never redistributed')
    p.add_argument('--source-catalog', type=Path, help='Dev36 public source IDs, with --private-cache-zip')
    p.add_argument('--output', required=True, type=Path)
    args = p.parse_args(argv)
    if args.source_catalog and not args.private_cache_zip:
        p.error('--source-catalog needs --private-cache-zip')
    if args.output.exists() or args.output.is_symlink():
        p.error('refusing to overwrite output')
    try:
        report = make_report(args.apk, cache=args.private_cache_zip, catalog=args.source_catalog)
    except (ValueError, OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        p.error(f'inspection failed: {type(exc).__name__}')
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print('Dev47 offline APK evidence report written; no native mapping inferred')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
