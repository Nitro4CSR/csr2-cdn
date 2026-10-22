"""Dev70: CSR2 6.8.0 crew loader completion -> scene visual setup trace.

This is a static, SHA-pinned ARM64 investigation; it does not execute the
client or observe the final paint. In particular, verifying named callsites
cannot rule out indirect methods, subsequent loads or runtime list edits.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct
from typing import Any

from .dev47_apk_paint_semantics import _section
from .dev48_native_paint_methods import _ELF, _slice
from .dev59_milestone_unlockables import _read_native
from .dev69_crew_garage_loader import inspect as previous_inspect, _branch_target

# Native 6.8.0 method bodies (RVA, bounded length, sha256).
_METHODS: dict[str, tuple[int, int, str]] = {
    'GarageCarLoader.AssetRequestCompleted': (
        0x33bcd80, 0x144, '85bd43bfec7bcc060c92bbe4bfa6bf4bee175e4565ec3077da56899a09cdacd5'),
    'GarageCarLoader.CarLoaded': (
        0x33bd754, 0x200, '9953932cb7663a0cadab6f3b41edf8e3e2638b514baafe45872484c3db581557'),
    'GarageCarVisuals.Setup': (
        0x33c13e0, 0x40c, '91fc580488739fbabe168144083f0c04d9090b0571dd2eb6386b11119f1b6887'),
    'SceneManagerGarage.CarLoaded': (
        0x3612398, 0x770, '86839f54471f7ccf0a2a04fe99c1b4ebaa89f421e775ac036d524902ab5e1134'),
}

# Name, method, PC, ARM64 word, expected direct B/BL destination (if any).
_SITES: dict[str, tuple[str, int, int, int | None]] = {
    'asset_request_can_tail_call_synchronous_completion': (
        'GarageCarLoader.AssetRequestCompleted', 0x33bcebc, 0x140002e9, 0x33bda60),
    'asset_request_can_start_async_car_load': (
        'GarageCarLoader.AssetRequestCompleted', 0x33bce8c, 0x97ee00aa, 0x2f3d134),
    'car_loaded_state_guard': (
        'GarageCarLoader.CarLoaded', 0x33bd7e4, 0x37000915, None),
    'car_loaded_requests_asset': (
        'GarageCarLoader.CarLoaded', 0x33bd8e4, 0x97edf79f, 0x2f3b760),
    'car_loaded_can_tail_call_asset_completed': (
        'GarageCarLoader.CarLoaded', 0x33bd94c, 0x17fffd0d, 0x33bcd80),
    'garage_visuals_captures_car_reference': (
        'GarageCarVisuals.Setup', 0x33c148c, 0xf9001275, None),
    'garage_visuals_sets_car_back_reference': (
        'GarageCarVisuals.Setup', 0x33c159c, 0xf9018ab3, None),
    'garage_visuals_configures_shader_lod': (
        'GarageCarVisuals.Setup', 0x33c15fc, 0x94110c17, 0x3804658),
    'garage_visuals_configures_lighting': (
        'GarageCarVisuals.Setup', 0x33c1614, 0x94110cc5, 0x3804928),
    'garage_visuals_configures_race_keyword': (
        'GarageCarVisuals.Setup', 0x33c1638, 0x94110e6b, 0x3804fe4),
    'garage_visuals_configures_plate': (
        'GarageCarVisuals.Setup', 0x33c164c, 0x94112e96, 0x380d0a4),
    'scene_calls_garage_visuals_setup': (
        'SceneManagerGarage.CarLoaded', 0x361292c, 0x97f6baad, 0x33c13e0),
    'scene_car_visuals_setup_car_argument': (
        'SceneManagerGarage.CarLoaded', 0x36129d0, 0xaa1403e1, None),
    'scene_car_visuals_setup_flag': (
        'SceneManagerGarage.CarLoaded', 0x36129c8, 0x52800022, None),
    'scene_calls_car_visuals_setup': (
        'SceneManagerGarage.CarLoaded', 0x36129d8, 0x9407bf61, 0x380275c),
    'scene_can_show_car_after_visual_setup': (
        'SceneManagerGarage.CarLoaded', 0x3612a08, 0x940013fb, 0x36179f4),
}


def _verify_managed_methods(meta: bytes, elf: _ELF) -> dict[str, dict[str, int | str]]:
    so, sl = _section(meta, 0x18, 1)
    to, tl = _section(meta, 0xa0, 0x58)
    mo, ml = _section(meta, 0x30, 36)
    strings = _slice(meta, so, sl)
    def name(i: int) -> str:
        if not 0 <= i < len(strings):
            raise ValueError('invalid managed string offset')
        end = strings.find(b'\0', i)
        if end < 0:
            raise ValueError('unterminated managed string')
        return strings[i:end].decode('utf8', 'replace')
    wanted: dict[str, dict[str, int]] = {}
    for fq, (addr, _, _) in _METHODS.items():
        cls, method = fq.split('.', 1)
        wanted.setdefault(cls, {})[method] = addr
    count, ptr = elf.find_module()
    found: dict[str, dict[str, int | str]] = {}
    for i in range(tl // 0x58):
        o = to + i * 0x58
        cls = name(struct.unpack_from('<I', meta, o)[0])
        if cls not in wanted:
            continue
        first = struct.unpack_from('<I', meta, o + 0x24)[0]
        n = struct.unpack_from('<H', meta, o + 0x40)[0]
        if first > ml // 36 or n > ml // 36 - first:
            raise ValueError('out-of-range method metadata')
        for j in range(first, first + n):
            row = mo + j * 36
            method = name(struct.unpack_from('<I', meta, row)[0])
            if method not in wanted[cls]:
                continue
            fq = cls + '.' + method
            token = struct.unpack_from('<I', meta, row + 24)[0]
            rid = token & 0xffffff
            if token >> 24 != 6 or not 1 <= rid <= count:
                raise ValueError('invalid method token: ' + fq)
            addr = elf.relative(ptr + (rid - 1) * 8)
            if addr != wanted[cls][method] or fq in found:
                raise ValueError('ambiguous or mismatched native pointer: ' + fq)
            found[fq] = {'rva': hex(addr), 'token_rid': rid}
    if set(found) != set(_METHODS):
        raise ValueError('missing named native method')
    return found


def audit_native(metadata: bytes, native: bytes) -> dict[str, Any]:
    if len(metadata) < 128 or struct.unpack_from('<II', metadata, 0) != (0xfab11baf, 31):
        raise ValueError('unsupported IL2CPP metadata')
    elf = _ELF(native)
    names = _verify_managed_methods(metadata, elf)
    bodies = {}
    methods = {}
    for fq, (addr, length, digest) in _METHODS.items():
        if not 0 < length <= 8192 or length % 4:
            raise ValueError('invalid bounded native span')
        body = _slice(native, elf.fileoff(addr, length, execute=True), length)
        actual = hashlib.sha256(body).hexdigest()
        if actual != digest:
            raise ValueError('native method fingerprint mismatch: ' + fq)
        bodies[fq] = body
        methods[fq] = {'rva': hex(addr), 'bounded_length': length, 'sha256': actual}
    sites = {}
    for label, (fq, at, expected, target) in _SITES.items():
        start, length, _ = _METHODS[fq]
        if not start <= at <= start + length - 4:
            raise ValueError('instruction outside bounded method')
        word = struct.unpack_from('<I', bodies[fq], at - start)[0]
        if word != expected:
            raise ValueError('native instruction mismatch: ' + label)
        if target is not None and _branch_target(word, at) != target:
            raise ValueError('native branch mismatch: ' + label)
        site = {'rva': hex(at), 'opcode': hex(word)}
        if target is not None:
            site['direct_target'] = hex(target)
        sites[label] = site
    # Direct B/BL scan in these bounded method bodies. Absence of a direct call
    # does NOT rule out virtual dispatch, indirect callsites, or later mutations.
    return {
        'methods': methods,
        'managed_pointer_matches': names,
        'verified_sites': sites,
        'scene_manager_calls_garage_visuals_setup_first': True,
        'scene_manager_calls_car_visuals_setup_afterwards': True,
        'garage_car_loader_asset_callbacks_observed': True,
        'crew_visuals_setup_is_not_generic_car_loader_override': True,
        'actual_runtime_scene_execution_observed': False,
        'post_setup_paint_list_unchanged_verified': False,
        'selected_paint_rendered_observed': False,
    }


def inspect(apk: Path, car_metadata_bundle: Path, visual_bundle: Path,
            cache_zip: Path, source_catalog: Path, *,
            vehicle: str = 'Ford_Mustang302_1970', paint_index: int = 15) -> dict[str, Any]:
    metadata, native = _read_native(apk)
    audit = audit_native(metadata, native)
    previous = previous_inspect(apk, car_metadata_bundle, visual_bundle,
                               cache_zip, source_catalog,
                               vehicle=vehicle, paint_index=paint_index)
    candidate = previous['paint_reconstruction']
    return {
        'status': 'dev70_crew_completion_to_car_visuals_setup_verified',
        'apk_native': audit,
        'car_key': vehicle,
        'source_database_version': '34011',
        'carinfo_is_tuner_stars_car': previous['carinfo_is_tuner_stars_car'],
        'milestone_scheme_id': previous['milestone_scheme_id'],
        'paint_reconstruction': {
            'received_index': candidate['received_index'],
            'conditional_candidate_paint_id': candidate['conditional_candidate_paint_id'],
            'conditional_candidate_label': candidate['conditional_candidate_label'],
            'production_mapping_verified': False,
            'runtime_paint_list_captured': False,
            'all_indirect_and_later_mutations_excluded': False,
        },
        'paint_index_zero': 'unresolved',
        'authenticated_gameplay_reads': 0,
        'network_requests': 0,
        'production_paint_mapping_changed': False,
        'player_identifiers_exported': False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for k in ('apk', 'car-metadata-bundle', 'visual-bundle', 'cache-zip', 'source-catalog', 'output'):
        parser.add_argument('--' + k, type=Path, required=True)
    parser.add_argument('--vehicle', default='Ford_Mustang302_1970')
    parser.add_argument('--paint-index', default=15, type=int)
    args = parser.parse_args(argv)
    if args.output.exists() or args.output.is_symlink():
        parser.error('refusing to overwrite output')
    result = inspect(args.apk, args.car_metadata_bundle, args.visual_bundle,
                     args.cache_zip, args.source_catalog,
                     vehicle=args.vehicle, paint_index=args.paint_index)
    with args.output.open('x', encoding='utf8') as f:
        json.dump(result, f, sort_keys=True, indent=2)
        f.write('\n')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
