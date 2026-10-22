"""Dev74: APK-only native guard analysis of gacha and aftermarket paint mutations.

Static, conservative intra-method evidence only. A reachable instruction does
not imply that any particular car executes it, and no runtime list is read.
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
from .dev54_initial_paint_setup import _decode_bl
from .dev59_milestone_unlockables import _read_native
from .dev71_crew_setup_paint_selection import _METHODS
from .dev72_tutorial_paint_writeback import _successors
from .dev73_tutorial_paint_list_paths import audit_native as audit_dev73, _method_reachable

# Exact 6.8.0 method pointer, bounded length and sha256 of entire bounded body.
_NEW_METHODS: dict[str, tuple[int, int, str]] = {
    'CarVisuals.ApplyGachaConfig': (
        0x38012a4, 0x78c, '0615fa062139322cc5345057f1d7436dd241f5d038278c73cca372621e3d8116'),
    'CarVisuals.AddAftermarketPaintsToCar': (
        0x3818cdc, 0x204, '52cc34693b48a400e8fc287441b441b5cc37874266a90878ea6a48205150ea64'),
}

# Label => (method name, address, exact ARM64 instruction, optional direct BL destination).
_SITES: dict[str, tuple[str, int, int, int | None]] = {
    'scene_gacha_validity_check': ('SceneManagerGarage.CarLoaded', 0x36126c0, 0x94082f2b, 0x381e36c),
    'scene_gacha_eligibility_skip': ('SceneManagerGarage.CarLoaded', 0x36126f4, 0x340008a8, None),
    'scene_gacha_config_index_limit': ('SceneManagerGarage.CarLoaded', 0x3612758, 0x540002ea, None),
    'scene_passes_garage_instance_to_gacha': ('SceneManagerGarage.CarLoaded', 0x36127a0, 0xaa1403e2, None),
    'scene_calls_gacha': ('SceneManagerGarage.CarLoaded', 0x36127ac, 0x9407babe, 0x38012a4),
    'scene_calls_setup_after_gacha': ('SceneManagerGarage.CarLoaded', 0x36129d8, 0x9407bf61, 0x380275c),
    'gacha_preserves_garage_argument': ('CarVisuals.ApplyGachaConfig', 0x38012cc, 0xaa0203f5, None),
    'gacha_existing_paint_selection': ('CarVisuals.ApplyGachaConfig', 0x38014a0, 0xb9011e60, None),
    'gacha_missing_paint_append': ('CarVisuals.ApplyGachaConfig', 0x3801584, 0xb9002101, None),
    'gacha_other_visual_list_append_1': ('CarVisuals.ApplyGachaConfig', 0x3801690, 0xb9002121, None),
    'gacha_other_visual_list_append_2': ('CarVisuals.ApplyGachaConfig', 0x3801798, 0xb9002121, None),
    'gacha_selects_appended_last_index': ('CarVisuals.ApplyGachaConfig', 0x38015c0, 0xb9011e68, None),
    'gacha_refreshes_paint': ('CarVisuals.ApplyGachaConfig', 0x38015c8, 0x940027cc, 0x380b4f8),
    'gacha_optional_garage_guard': ('CarVisuals.ApplyGachaConfig', 0x3801858, 0xb4000df5, None),
    'gacha_writes_garage_paint_index': ('CarVisuals.ApplyGachaConfig', 0x3801878, 0xb9006ea8, None),
    'aftermarket_paint_membership_check': ('CarVisuals.AddAftermarketPaintsToCar', 0x3818e44, 0x944965de, 0x4a725bc),
    'aftermarket_skips_present_ids': ('CarVisuals.AddAftermarketPaintsToCar', 0x3818e48, 0x37000380, None),
    'aftermarket_appends_absent_id': ('CarVisuals.AddAftermarketPaintsToCar', 0x3818e9c, 0xb9002101, None),
    'aftermarket_loop_continues': ('CarVisuals.AddAftermarketPaintsToCar', 0x3818ec4, 0x54fffa4b, None),
    'refresh_loads_index': ('CarVisuals.ForceUpdateOfCarPaint', 0x380b5f0, 0xb9411e61, None),
    'refresh_loads_list_size': ('CarVisuals.ForceUpdateOfCarPaint', 0x380b60c, 0xb9401808, None),
    'refresh_branches_if_index_in_range': ('CarVisuals.ForceUpdateOfCarPaint', 0x380b614, 0x5400014b, None),
    'refresh_calls_aftermarket_when_out_of_range': ('CarVisuals.ForceUpdateOfCarPaint', 0x380b61c, 0x940035b0, 0x3818cdc),
    'refresh_checks_index_again_after_append': ('CarVisuals.ForceUpdateOfCarPaint', 0x380b638, 0x5400032a, None),
    'refresh_paint_id_positional_lookup': ('CarVisuals.ForceUpdateOfCarPaint', 0x380b648, 0x94499a43, 0x4a71f54),
}


def _managed_pointers(metadata: bytes, elf: _ELF) -> dict[str, int]:
    """Cross-check two native entrypoints against IL2CPP managed method tokens."""
    string_off, string_len = _section(metadata, 0x18, 1)
    type_off, type_len = _section(metadata, 0xa0, 0x58)
    method_off, method_len = _section(metadata, 0x30, 36)
    strings = _slice(metadata, string_off, string_len)
    def name(offset: int) -> str:
        if not 0 <= offset < len(strings):
            raise ValueError('invalid managed string offset')
        end = strings.find(b'\0', offset)
        if end < 0:
            raise ValueError('unterminated managed string')
        return strings[offset:end].decode('utf-8', 'replace')
    count, pointer_table = elf.find_module()
    found: dict[str, int] = {}
    for i in range(type_len // 0x58):
        row = type_off + i * 0x58
        if name(struct.unpack_from('<I', metadata, row)[0]) != 'CarVisuals':
            continue
        first = struct.unpack_from('<I', metadata, row + 0x24)[0]
        n = struct.unpack_from('<H', metadata, row + 0x40)[0]
        if first > method_len // 36 or n > method_len // 36 - first:
            raise ValueError('invalid managed method range')
        for j in range(first, first + n):
            mrow = method_off + 36 * j
            fq = 'CarVisuals.' + name(struct.unpack_from('<I', metadata, mrow)[0])
            if fq not in _NEW_METHODS:
                continue
            token = struct.unpack_from('<I', metadata, mrow + 24)[0]
            rid = token & 0xffffff
            if token >> 24 != 6 or not 1 <= rid <= count:
                raise ValueError('invalid managed method token')
            ptr = elf.relative(pointer_table + (rid - 1) * 8)
            if fq in found or ptr != _NEW_METHODS[fq][0]:
                raise ValueError('managed/native pointer mismatch: ' + fq)
            found[fq] = ptr
    if set(found) != set(_NEW_METHODS):
        raise ValueError('missing gacha or aftermarket managed method')
    return found


def audit_native(metadata: bytes, native: bytes) -> dict[str, Any]:
    """Audit byte-pinned method bodies and CFG witnesses; fail closed on changes."""
    # Retain all source, CFG, post-setup and version checks from Dev73.
    prior = audit_dev73(metadata, native)
    elf = _ELF(native)
    managed = _managed_pointers(metadata, elf)
    methods = {**_METHODS, **_NEW_METHODS}
    bodies: dict[str, bytes] = {}
    for fq, (base, length, digest) in methods.items():
        if length % 4 or length <= 0 or length > 8192:
            raise ValueError('invalid bounded native method length')
        body = _slice(native, elf.fileoff(base, length, execute=True), length)
        if hashlib.sha256(body).hexdigest() != digest:
            raise ValueError('bounded native fingerprint changed: ' + fq)
        bodies[fq] = body
    instructions: dict[str, dict[str, str]] = {}
    for label, (owner, pc, word, bl_target) in _SITES.items():
        base, length, _ = methods[owner]
        if not base <= pc <= base + length - 4 or (pc - base) % 4:
            raise ValueError('invalid pinned instruction location: ' + label)
        actual = struct.unpack_from('<I', bodies[owner], pc - base)[0]
        if actual != word or (bl_target is not None and _decode_bl(word, pc) != bl_target):
            raise ValueError('pinned native instruction mismatch: ' + label)
        instructions[label] = {'rva': hex(pc), 'word': hex(word)}
        if bl_target is not None:
            instructions[label]['direct_target'] = hex(bl_target)
    # Both optional and action branches are reachable in the bounded method-level CFG.
    reachable: dict[str, set[int]] = {}
    for key in ('SceneManagerGarage.CarLoaded', 'CarVisuals.ApplyGachaConfig',
                'CarVisuals.AddAftermarketPaintsToCar', 'CarVisuals.ForceUpdateOfCarPaint'):
        reachable[key] = _method_reachable(bodies[key], methods[key][0])
    for label, (owner, pc, _, _) in _SITES.items():
        if pc not in reachable[owner]:
            raise ValueError('native CFG witness absent: ' + label)

    # Check actual alternate edges; the calls are optional, not unconditional.
    gate_addr, limit_addr = 0x36126f4, 0x3612758
    scene = bodies['SceneManagerGarage.CarLoaded']
    gate_word = struct.unpack_from('<I', scene, gate_addr - methods['SceneManagerGarage.CarLoaded'][0])[0]
    limit_word = struct.unpack_from('<I', scene, limit_addr - methods['SceneManagerGarage.CarLoaded'][0])[0]
    if _successors(gate_addr, gate_word) != (0x3612808, 0x36126f8):
        raise ValueError('gacha eligibility bypass edge changed')
    if _successors(limit_addr, limit_word) != (0x36127b4, 0x361275c):
        raise ValueError('gacha config index bound edge changed')
    start, _, _ = methods['SceneManagerGarage.CarLoaded']
    if 0x36129d8 not in _method_reachable(scene, start, 0x3612808):
        raise ValueError('setup absent from gacha-bypassed continuation')
    # ForceUpdate branches directly to positional lookup for in-range values.
    branch_at = 0x380b614
    force = bodies['CarVisuals.ForceUpdateOfCarPaint']
    force_word = struct.unpack_from('<I', force, branch_at - methods['CarVisuals.ForceUpdateOfCarPaint'][0])[0]
    if _successors(branch_at, force_word) != (0x380b63c, 0x380b618):
        raise ValueError('aftermarket call branch is not index-bound guarded')
    if _successors(0x3818e48, _SITES['aftermarket_skips_present_ids'][2]) != (0x3818eb8, 0x3818e4c):
        raise ValueError('aftermarket membership skip changed')

    return {
        'status': 'dev74_native_gacha_and_aftermarket_mutation_guards',
        'client': 'CSR2 6.8.0',
        'verified_source_enum': 'Tutorial', 'source_numeric_value': 1,
        'prior_dev73_source_specific_exclusions_preserved':
            (prior['intra_method_cfg']['pre_selection_append_sites_reachable_for_tutorial'] == [] and
             prior['intra_method_cfg']['garage_paint_index_writebacks_reachable_for_tutorial'] == []),
        'scene_gacha_branch': {
            'eligibility_runtime_guard_at': '0x36126f4',
            'eligibility_skip_target': '0x3612808',
            'config_index_runtime_guard_at': '0x3612758',
            'config_index_skip_target': '0x36127b4',
            'callsite_at': '0x36127ac',
            'setup_after_at': '0x36129d8',
            'can_skip_gacha_and_continue_to_setup': True,
            'gacha_executed_for_tutorial_observed': False,
            'no_tutorial_specific_exclusion_proved': True,
        },
        'gacha_mutation_capabilities': {
            'paint_list_field': 'CarVisuals+0x70',
            'paint_index_field': 'CarVisuals+0x11c',
            'garage_index_field': 'CarGarageInstance+0x6c',
            'paint_list_append_at': '0x3801584',
            'other_visual_list_append_sites': ['0x3801690', '0x3801798'],
            'can_select_existing_id_at': '0x38014a0',
            'can_select_appended_last_index_at': '0x38015c0',
            'can_refresh_paint_at': '0x38015c8',
            'can_write_selected_index_to_passed_garage_at': '0x3801878',
            'all_actions_statically_reachable_not_observed': True,
        },
        'aftermarket_mutation_capabilities': {
            'selected_index_compared_to_current_list_count_at': '0x380b610',
            'in_range_skips_aftermarket_call_to': '0x380b63c',
            'out_of_range_can_call_add_aftermarket_at': '0x380b61c',
            'rechecks_selected_index_against_list_count_at': '0x380b638',
            'conditional_membership_helper_at': '0x3818e44',
            'already_present_branch_skips_append_to': '0x3818eb8',
            'new_paint_id_append_at': '0x3818e9c',
            'paint_lookup_after_guards_at': '0x380b648',
            'runtime_list_size_known': False,
            'runtime_aftermarket_input_known': False,
        },
        'new_managed_native_methods': {
            fq: {'rva': hex(addr), 'bounded_length': _NEW_METHODS[fq][1],
                 'sha256': _NEW_METHODS[fq][2]}
            for fq, addr in sorted(managed.items())
        },
        'pinned_instruction_sites': instructions,
        'runtime_ordered_paint_list_captured': False,
        'actual_gacha_branch_outcome_observed': False,
        'all_other_indirect_and_later_mutations_excluded': False,
        'production_paint_mapping_verified': False,
        'paint_index_15_conditional_candidate': 1323,
        'candidate_from_prior_bundles_not_revalidated': True,
        'paint_index_0': 'unresolved',
        'production_mappings_changed': False,
        'network_requests': 0, 'gameplay_reads': 0, 'private_roster_read': False,
    }


def inspect(apk: Path) -> dict[str, Any]:
    return audit_native(*_read_native(apk))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apk', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(argv)
    if args.output.exists() or args.output.is_symlink():
        parser.error('refusing to overwrite existing report')
    try:
        result = inspect(args.apk)
        serialized = json.dumps(result, sort_keys=True, indent=2) + '\n'
        if len(serialized.encode('utf8')) > 150_000:
            raise ValueError('bounded evidence size exceeded')
        with args.output.open('x', encoding='utf-8') as target:
            target.write(serialized)
    except (OSError, ValueError, KeyError, struct.error) as error:
        parser.error(str(error))
    print('Dev74: gacha may modify selected/list paint; runtime Tutorial branch unknown.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
