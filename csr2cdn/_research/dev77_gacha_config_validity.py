"""Dev77: APK-only, fingerprint-pinned gacha-config sentinel validity check.

No game execution or private profile is involved.  Synthetic examples are not
observed Mustang state; this does not verify any production paint mapping.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct
from typing import Any, Sequence

from .dev48_native_paint_methods import _ELF, _slice
from .dev59_milestone_unlockables import _read_native
from .dev72_tutorial_paint_writeback import _successors
from .dev75_gacha_eligibility import model_gacha_decision
from .dev76_delivery_tuple_provenance import audit_native as audit_dev76

# Contiguous, independently hashed CarVisualsGachaConfig.IsValid ARM64 method.
_BASE = 0x381E36C
_LENGTH = 0x44
_SHA256 = '28dbb5049711491008f44b0fc7c2f55edc816f39c6a1f045053177b11f2b808e'
_SENTINEL = 0x7FFFFFFF
_FIELDS = (0x1C, 0x20, 0x24, 0x28)

# Exact opcodes in instruction order, not just descriptive labels.
_SITES: dict[str, tuple[int, int]] = {
    'first_field_read': (0x381E36C, 0xB9401C09),
    'int32_max_constant_first': (0x381E370, 0x12B00008),
    'first_comparison': (0x381E374, 0x6B08013F),
    'first_non_sentinel_return_true': (0x381E378, 0x54000181),
    'second_field_read': (0x381E37C, 0xB9402009),
    'second_comparison': (0x381E380, 0x6B08013F),
    'second_non_sentinel_return_true': (0x381E384, 0x54000121),
    'third_field_read': (0x381E388, 0xB9402409),
    'int32_max_constant_third': (0x381E38C, 0x12B00008),
    'third_comparison': (0x381E390, 0x6B08013F),
    'third_non_sentinel_return_true': (0x381E394, 0x540000A1),
    'fourth_field_read': (0x381E398, 0xB9402809),
    'fourth_comparison': (0x381E39C, 0x6B08013F),
    'fourth_comparison_sets_validity': (0x381E3A0, 0x1A9F07E0),
    'return_from_final_comparison': (0x381E3A4, 0xD65F03C0),
    'return_true_constant': (0x381E3A8, 0x52800020),
    'return_true': (0x381E3AC, 0xD65F03C0),
}
_BRANCH_EDGES: dict[str, tuple[int, int]] = {
    'first_non_sentinel_return_true': (0x381E3A8, 0x381E37C),
    'second_non_sentinel_return_true': (0x381E3A8, 0x381E388),
    'third_non_sentinel_return_true': (0x381E3A8, 0x381E398),
}


def model_config_validity(fields: Sequence[int]) -> dict[str, Any]:
    """Small normal non-null synthetic model of four 32-bit sentinel fields."""
    if (not isinstance(fields, (tuple, list)) or len(fields) != 4 or
        any(type(x) is not int or x < -(1 << 31) or x > 0xFFFFFFFF for x in fields)):
        raise ValueError('expected exactly four 32-bit integer fields')
    values = [x & 0xFFFFFFFF for x in fields]
    first_non_sentinel = next((i for i, x in enumerate(values) if x != _SENTINEL), None)
    valid = first_non_sentinel is not None
    return {
        'fields_as_unsigned32': values,
        'first_non_sentinel_field': first_non_sentinel,
        'is_valid': valid,
        'all_four_int32_max': not valid,
        'synthetic_only': True,
    }


def model_fallback(*, flag_0x160: bool, fields: Sequence[int],
                   garage_word_0xb0: int, pop_result: int = 0) -> dict[str, Any]:
    """Compose only the known Dev75 eligibility model, not a runtime replay."""
    validity = model_config_validity(fields)
    if type(flag_0x160) is not bool:
        raise ValueError('flag must be bool')
    decision = model_gacha_decision(
        pop_result, flag_0x160=flag_0x160,
        config_is_valid=validity['is_valid'], garage_word_0xb0=garage_word_0xb0,
        secondary_filter_rejects=False, config_count=1, config_entry_present=True)
    return {
        'config_validity': validity,
        'fallback_eligibility': decision['fallback_sentinel_gate'],
        'positive_delivery_eligibility': decision['positive_pop_result'],
        'combined_eligibility': decision['eligibility_gate'],
        'can_reach_gacha_call_under_synthetic_inputs': decision['can_reach_gacha_call_under_inputs'],
        'unmodeled_actual_runtime_secondary_filter': True,
        'synthetic_only': True,
    }


def audit_native(metadata: bytes, native: bytes) -> dict[str, Any]:
    prior = audit_dev76(metadata, native)
    if prior['production_mappings_changed'] or prior['runtime_ordered_paint_list_captured']:
        raise ValueError('Dev76 static-only guarantees changed')
    if prior['previous_dev75_metadata_pointer_preserved'] is not True:
        raise ValueError('Dev75 managed pointer verification not preserved')
    # Dev75 independently resolves CarVisualsGachaConfig.IsValid in IL2CPP metadata.
    # Dev77 pins and inspects the actual callee body, not only the BL target.
    elf = _ELF(native)
    body = _slice(native, elf.fileoff(_BASE, _LENGTH, execute=True), _LENGTH)
    if hashlib.sha256(body).hexdigest() != _SHA256:
        raise ValueError('CarVisualsGachaConfig.IsValid native fingerprint changed')
    pinned: dict[str, dict[str, str]] = {}
    for name, (addr, word) in _SITES.items():
        if addr < _BASE or addr + 4 > _BASE + _LENGTH or (addr - _BASE) % 4:
            raise ValueError('site outside method: ' + name)
        actual = struct.unpack_from('<I', body, addr - _BASE)[0]
        if actual != word:
            raise ValueError('native opcode changed: ' + name)
        pinned[name] = {'rva': hex(addr), 'word': hex(word)}
    for name, edges in _BRANCH_EDGES.items():
        pc, word = _SITES[name]
        if _successors(pc, word) != edges:
            raise ValueError('native conditional edge changed: ' + name)
    # Verify that all four LDR W9, [X0, +offset] operands match the expected
    # base register, destination register, and byte offsets (not only site order).
    for i, label in enumerate(('first_field_read', 'second_field_read',
                               'third_field_read', 'fourth_field_read')):
        word = _SITES[label][1]
        if ((word & 0xFFC003FF) != 0xB9400009 or
            ((word >> 10) & 0xFFF) * 4 != _FIELDS[i]):
            raise ValueError('sentinel field read changed: ' + label)
    examples = {
        'all_four_sentinel': model_config_validity([_SENTINEL] * 4),
        'first_field_differs': model_config_validity([0, _SENTINEL, _SENTINEL, _SENTINEL]),
        'last_field_differs': model_config_validity([_SENTINEL, _SENTINEL, _SENTINEL, -1]),
        'fallback_when_all_sentinel': model_fallback(flag_0x160=True,
            fields=[_SENTINEL] * 4, garage_word_0xb0=-(1 << 31)),
        'valid_config_suppresses_fallback': model_fallback(flag_0x160=True,
            fields=[0, _SENTINEL, _SENTINEL, _SENTINEL], garage_word_0xb0=-(1 << 31)),
        'invalid_config_without_flag': model_fallback(flag_0x160=False,
            fields=[_SENTINEL] * 4, garage_word_0xb0=-(1 << 31)),
    }
    return {
        'status': 'dev77_gacha_config_four_sentinel_validity_static',
        'client': 'CSR2 6.8.0',
        'managed_method': 'CarVisualsGachaConfig.IsValid',
        'prior_dev75_managed_pointer_verified': True,
        'previous_dev72_76_native_chain_passed': True,
        'native_method': {'rva': hex(_BASE), 'bounded_length': _LENGTH,
                          'sha256': _SHA256},
        'pinned_instructions': pinned,
        'native_branch_edges': {k: [hex(x) for x in v]
                                for k, v in sorted(_BRANCH_EDGES.items())},
        'validity_predicate': {
            'normal_non_null_object_path_only': True,
            'fields_offset_hex': [hex(x) for x in _FIELDS],
            'int32_max_sentinel': _SENTINEL,
            'is_invalid_iff_all_four_equal_sentinel': True,
            'any_one_non_sentinel_means_valid': True,
            'source_enum_directly_checked': False,
            'paint_list_directly_accessed': False,
            'dev75_fallback_also_requires_flag_and_int32_min_garage_word': True,
        },
        'synthetic_scenarios_not_runtime_observations': examples,
        'actual_four_config_fields_observed': False,
        'actual_tutorial_mustang_gacha_eligibility_observed': False,
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
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--apk', required=True, type=Path)
    p.add_argument('--output', required=True, type=Path)
    args = p.parse_args(argv)
    if args.output.exists() or args.output.is_symlink():
        p.error('refusing to overwrite existing evidence output')
    try:
        report = inspect(args.apk)
        body = json.dumps(report, sort_keys=True, indent=2) + '\n'
        if len(body.encode('utf-8')) > 150_000:
            raise ValueError('oversized native evidence')
        with args.output.open('x', encoding='utf-8') as stream:
            stream.write(body)
    except (OSError, ValueError, KeyError, struct.error) as exc:
        p.error(str(exc))
    print('Dev77: validity is four INT32_MAX sentinel fields; Mustang runtime state remains unobserved.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
