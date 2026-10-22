"""Dev75: pinned, APK-only gacha eligibility predicate and index-gate audit.

The pure predicate model illustrates possible machine-state outcomes. It does
not reconstruct the Tutorial Mustang's runtime inputs or executed branches.
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
from .dev74_gacha_paint_mutation import audit_native as audit_dev74

# Label -> address, expected native word, optional known direct BL target.
_SITES: dict[str, tuple[int, int, int | None]] = {
    'garage_key_load': (0x3612694, 0xb9401a81, None),
    'delivery_list_pop': (0x361269c, 0x97fb5097, 0x34e68f8),
    'load_garage_flag': (0x36126a0, 0x39458288, None),
    'preserve_pop_result': (0x36126a4, 0xaa0003fa, None),
    'flag_zero_skips_validation': (0x36126ac, 0x34000128, None),
    'load_config_for_validation': (0x36126b0, 0xf940b680, None),
    'config_validation_call': (0x36126c0, 0x94082f2b, 0x381e36c),
    'invalid_config_takes_fallback': (0x36126c4, 0x360000a0, None),
    'valid_config_zeroes_fallback': (0x36126c8, 0x2a1f03e8, None),
    'fallback_reads_garage_word': (0x36126d8, 0xb940b288, None),
    'fallback_compares_min_int': (0x36126e0, 0x6b09011f, None),
    'fallback_equals_min_int': (0x36126e4, 0x1a9f17e8, None),
    'pop_positive_compare': (0x36126e8, 0x7100035f, None),
    'pop_positive_boolean': (0x36126ec, 0x1a9fd7e9, None),
    'combine_eligibility_flags': (0x36126f0, 0x2a090108, None),
    'eligibility_skip': (0x36126f4, 0x340008a8, None),
    'pop_upper_word_extract': (0x3612708, 0xd360ff48, None),
    'pop_positive_selects_index': (0x361270c, 0x1a9fc11c, None),
    'negative_index_skip': (0x361273c, 0x37f803dc, None),
    'secondary_filter_skip': (0x3612740, 0x370003a0, None),
    'paint_gacha_config_count': (0x3612750, 0xb9401808, None),
    'config_index_comparison': (0x3612754, 0x6b08039f, None),
    'config_index_bound_skip': (0x3612758, 0x540002ea, None),
    'config_entry_lookup': (0x361276c, 0x9452c92d, 0x4ac4c20),
    'missing_config_entry_skip': (0x3612770, 0xb4000220, None),
    'pop_positive_retest': (0x361277c, 0x7100035f, None),
    'pop_positive_argument': (0x361278c, 0x1a9fd7fa, None),
    'selected_gacha_index_setter': (0x3612790, 0x9407ef27, 0x380e42c),
    'pass_garage_instance': (0x36127a0, 0xaa1403e2, None),
    'pass_pop_positive_flag': (0x36127a4, 0x2a1a03e3, None),
    'apply_gacha': (0x36127ac, 0x9407babe, 0x38012a4),
    'clear_one_shot_flag': (0x36127b0, 0x3905829f, None),
}
_EXPECTED_METHODS = {
    'PlayerProfile.PopCarIfInDeliveryWaitingList': 0x34e68f8,
    'CarVisualsGachaConfig.IsValid': 0x381e36c,
    'CarVisuals.set_CurrentGachaConfigIndex': 0x380e42c,
}
_BRANCH_TARGETS = {
    'flag_zero_skips_validation': (0x36126d0, 0x36126b0),
    'invalid_config_takes_fallback': (0x36126d8, 0x36126c8),
    'eligibility_skip': (0x3612808, 0x36126f8),
    'negative_index_skip': (0x36127b4, 0x3612740),
    'secondary_filter_skip': (0x36127b4, 0x3612744),
    'config_index_bound_skip': (0x36127b4, 0x361275c),
    'missing_config_entry_skip': (0x36127b4, 0x3612774),
}


def _lookup_managed_methods(meta: bytes, elf: _ELF) -> dict[str, int]:
    """Verify method names + pointers from v31 IL2CPP metadata, not disassembly labels."""
    s_off, s_len = _section(meta, 0x18, 1)
    t_off, t_len = _section(meta, 0xa0, 0x58)
    m_off, m_len = _section(meta, 0x30, 36)
    strings = _slice(meta, s_off, s_len)
    def name(offset: int) -> str:
        if not 0 <= offset < len(strings):
            raise ValueError('invalid method name offset')
        end = strings.find(b'\0', offset)
        if end < 0:
            raise ValueError('unterminated method name')
        return strings[offset:end].decode('utf-8', 'replace')
    count, pointer_base = elf.find_module()
    found: dict[str, int] = {}
    wanted_types = {fq.split('.')[0] for fq in _EXPECTED_METHODS}
    for row in range(t_len // 0x58):
        to = t_off + 0x58 * row
        typ = name(struct.unpack_from('<I', meta, to)[0])
        if typ not in wanted_types:
            continue
        first = struct.unpack_from('<I', meta, to + 0x24)[0]
        method_count = struct.unpack_from('<H', meta, to + 0x40)[0]
        if first > m_len // 36 or method_count > m_len // 36 - first:
            raise ValueError('out of bounds metadata method range')
        for idx in range(first, first + method_count):
            mo = m_off + idx * 36
            fq = typ + '.' + name(struct.unpack_from('<I', meta, mo)[0])
            if fq not in _EXPECTED_METHODS:
                continue
            token = struct.unpack_from('<I', meta, mo + 24)[0]
            rid = token & 0xffffff
            if token >> 24 != 6 or not 1 <= rid <= count:
                raise ValueError('unexpected native method token')
            address = elf.relative(pointer_base + (rid - 1) * 8)
            if fq in found or address != _EXPECTED_METHODS[fq]:
                raise ValueError('managed/native pointer mismatch: ' + fq)
            found[fq] = address
    if found != _EXPECTED_METHODS:
        raise ValueError('missing expected managed methods')
    return found


def _signed32(value: int) -> int:
    value &= 0xffffffff
    return value - 0x100000000 if value & 0x80000000 else value


def model_gacha_decision(
    pop_result: int, *, flag_0x160: bool, config_is_valid: bool,
    garage_word_0xb0: int, secondary_filter_rejects: bool,
    config_count: int, config_entry_present: bool,
) -> dict[str, Any]:
    """Synthetic instruction-level model, *not* a car-specific runtime resolver.

    Only normal non-null object paths are modeled. config_is_valid corresponds
    to the low bit returned by the native IsValid call when flag_0x160 is set.
    """
    if not 0 <= pop_result < 1 << 64 or not 0 <= config_count <= 1_000_000:
        raise ValueError('invalid synthetic register input')
    if not -(1 << 31) <= garage_word_0xb0 < 1 << 32:
        raise ValueError('invalid synthetic garage field')
    pop_positive = _signed32(pop_result) > 0
    fallback = bool(flag_0x160 and not config_is_valid and
                    _signed32(garage_word_0xb0) == -(1 << 31))
    eligible = pop_positive or fallback
    selected_index = _signed32(pop_result >> 32) if pop_positive else 0
    if not eligible:
        stop = 'eligibility_skip_0x36126f4'
    elif selected_index < 0:
        stop = 'negative_index_skip_0x361273c'
    elif secondary_filter_rejects:
        stop = 'secondary_filter_skip_0x3612740'
    elif selected_index >= config_count:
        stop = 'config_bounds_skip_0x3612758'
    elif not config_entry_present:
        stop = 'null_config_skip_0x3612770'
    else:
        stop = 'can_reach_call_0x36127ac'
    return {
        'positive_pop_result': pop_positive,
        'fallback_sentinel_gate': fallback,
        'eligibility_gate': eligible,
        'selected_gacha_config_index': selected_index,
        'normal_path_outcome': stop,
        'can_reach_gacha_call_under_inputs': stop == 'can_reach_call_0x36127ac',
        'synthetic_inputs_only': True,
    }


def audit_native(meta: bytes, native: bytes) -> dict[str, Any]:
    prev = audit_dev74(meta, native)
    if not prev['prior_dev73_source_specific_exclusions_preserved']:
        raise ValueError('previous Tutorial source proof changed')
    elf = _ELF(native)
    methods = _lookup_managed_methods(meta, elf)
    base, length, digest = _METHODS['SceneManagerGarage.CarLoaded']
    body = _slice(native, elf.fileoff(base, length, execute=True), length)
    if hashlib.sha256(body).hexdigest() != digest:
        raise ValueError('scene method fingerprint changed')
    pinned: dict[str, dict[str, str]] = {}
    for label, (pc, expected_word, target) in _SITES.items():
        if not base <= pc <= base + length - 4 or (pc - base) % 4:
            raise ValueError('native instruction site outside pinned method')
        word = struct.unpack_from('<I', body, pc - base)[0]
        if word != expected_word or (target is not None and _decode_bl(word, pc) != target):
            raise ValueError('native instruction mismatch: ' + label)
        pinned[label] = {'rva': hex(pc), 'word': hex(word)}
        if target is not None:
            pinned[label]['direct_target'] = hex(target)
    for label, edges in _BRANCH_TARGETS.items():
        pc, word, _ = _SITES[label]
        if _successors(pc, word) != edges:
            raise ValueError('native guard branch changed: ' + label)
    # Explicit marker of the unsigned high-word extraction after a signed
    # low-word compare; bound checks are on the selected config index, not paint.
    if _SITES['pop_positive_compare'][0] >= _SITES['pop_positive_selects_index'][0]:
        raise ValueError('pop result guard order changed')
    scenarios = {
        'no_positive_pop_no_fallback': model_gacha_decision(0, flag_0x160=False, config_is_valid=False,
            garage_word_0xb0=0, secondary_filter_rejects=False, config_count=2, config_entry_present=True),
        'positive_pop_in_range': model_gacha_decision((1 << 32) | 1, flag_0x160=False,
            config_is_valid=True, garage_word_0xb0=0, secondary_filter_rejects=False,
            config_count=2, config_entry_present=True),
        'fallback_can_choose_index_zero': model_gacha_decision(0, flag_0x160=True,
            config_is_valid=False, garage_word_0xb0=-(1 << 31),
            secondary_filter_rejects=False, config_count=1, config_entry_present=True),
        'positive_pop_index_out_of_bounds': model_gacha_decision((4 << 32) | 1,
            flag_0x160=False, config_is_valid=True, garage_word_0xb0=0,
            secondary_filter_rejects=False, config_count=2, config_entry_present=True),
        'positive_pop_negative_high_word': model_gacha_decision((0xffffffff << 32) | 1,
            flag_0x160=False, config_is_valid=True, garage_word_0xb0=0,
            secondary_filter_rejects=False, config_count=2, config_entry_present=True),
        'secondary_filter_rejects': model_gacha_decision(1, flag_0x160=False,
            config_is_valid=True, garage_word_0xb0=0, secondary_filter_rejects=True,
            config_count=1, config_entry_present=True),
        'missing_config_entry': model_gacha_decision(1, flag_0x160=False,
            config_is_valid=True, garage_word_0xb0=0, secondary_filter_rejects=False,
            config_count=1, config_entry_present=False),
    }
    return {
        'status': 'dev75_gacha_eligibility_static_predicate_and_guards',
        'client': 'CSR2 6.8.0',
        'verified_source_enum': 'Tutorial', 'source_numeric_value': 1,
        'previous_setup_source_exclusions_preserved': True,
        'managed_method_pointers': {fq:hex(ptr) for fq,ptr in sorted(methods.items())},
        'scene_method': {'rva':hex(base), 'bounded_length':length, 'sha256':digest},
        'pinned_instructions': pinned,
        'branch_edges': {k: [hex(x) for x in v] for k,v in sorted(_BRANCH_TARGETS.items())},
        'eligibility_predicate': {
            'delivery_pop_result_low32_signed_gt_zero': True,
            'or_fallback_when_flag_0x160_set_and_config_invalid_and_garage_word_0xb0_is_int32_min': True,
            'fallback_compared_value': '-2147483648',
            'source_enum_compared_directly_at_this_gate': False,
            'possible_indirect_runtime_source_dependence_excluded': False,
            'selected_config_index_when_positive': 'signed upper 32 bits of pop result',
            'selected_config_index_when_nonpositive': 0,
            'selected_config_index_is_paint_index': False,
            'additional_filters_before_gacha_call': [
                'negative selected config index', 'secondary validation/filter bit',
                'selected config index >= config count', 'null selected config entry',
            ],
            'normal_gacha_call_return_clears_flag_at': '0x36127b0',
        },
        'synthetic_scenarios_not_runtime_observations': scenarios,
        'actual_pop_result_observed': False,
        'actual_gacha_branch_outcome_observed': False,
        'runtime_ordered_paint_list_captured': False,
        'production_paint_mapping_verified': False,
        'paint_index_15_conditional_candidate': 1323,
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
        parser.error('refusing to overwrite an existing report')
    try:
        report = inspect(args.apk)
        payload = json.dumps(report, sort_keys=True, indent=2) + '\n'
        if len(payload.encode('utf-8')) > 150_000:
            raise ValueError('evidence exceeds bounded size')
        with args.output.open('x', encoding='utf-8') as f:
            f.write(payload)
    except (OSError, ValueError, KeyError, struct.error) as exc:
        parser.error(str(exc))
    print('Dev75: gacha eligibility depends on runtime delivery/garage state; Tutorial outcome unknown.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
