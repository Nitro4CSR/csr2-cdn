"""Dev76: APK-only, SHA-pinned provenance of the gacha delivery-result tuple.

This is a bounded *static* native analysis, not a read of any live profile.
Synthetic list examples illustrate exact index use but are not runtime evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct
from typing import Any, Sequence

from .dev48_native_paint_methods import _ELF, _slice
from .dev54_initial_paint_setup import _decode_bl
from .dev59_milestone_unlockables import _read_native
from .dev72_tutorial_paint_writeback import _successors
from .dev75_gacha_eligibility import audit_native as audit_dev75

# Bounded native method span and two-integer constructor, pinned to CSR2 6.8.0.
_NATIVE_SPANS = {
    'PlayerProfile.PopCarIfInDeliveryWaitingList': (
        0x34e68f8, 0x200,
        'f9614c920f5ca14ba84d87a49f291207656e6aa805d4d8f74b1f401bdf0c3af4'),
    'delivery_pair_constructor': (
        0x49affb0, 8,
        '73109c1402501dc23c92eec28460f747d6b135f585b5baa3d3ec3efc2b0a3ddc'),
}

# Label -> (owner, RVA, expected word, optional direct BL target).
_SITES: dict[str, tuple[str, int, int, int | None]] = {
    'first_list_from_profile': ('PlayerProfile.PopCarIfInDeliveryWaitingList', 0x34e69b0, 0xf943a114, None),
    'first_list_count': ('PlayerProfile.PopCarIfInDeliveryWaitingList', 0x34e69bc, 0xb9401a89, None),
    'first_list_empty_to_sentinel': ('PlayerProfile.PopCarIfInDeliveryWaitingList', 0x34e69c4, 0x34000809, None),
    'second_list_from_profile': ('PlayerProfile.PopCarIfInDeliveryWaitingList', 0x34e69c8, 0xf943a508, None),
    'second_list_empty_to_sentinel': ('PlayerProfile.PopCarIfInDeliveryWaitingList', 0x34e69d4, 0x34000788, None),
    'computed_index_lookup': ('PlayerProfile.PopCarIfInDeliveryWaitingList', 0x34e6a00, 0x942cc0f8, 0x4016de0),
    'computed_negative_index_to_sentinel': ('PlayerProfile.PopCarIfInDeliveryWaitingList', 0x34e6a1c, 0x37f80540, None),
    'preserve_computed_index': ('PlayerProfile.PopCarIfInDeliveryWaitingList', 0x34e6a28, 0x2a0003f4, None),
    'first_list_reloaded': ('PlayerProfile.PopCarIfInDeliveryWaitingList', 0x34e6a2c, 0xf943a100, None),
    'first_item_uses_position_zero': ('PlayerProfile.PopCarIfInDeliveryWaitingList', 0x34e6a3c, 0x2a1f03e1, None),
    'first_list_position_zero_read': ('PlayerProfile.PopCarIfInDeliveryWaitingList', 0x34e6a44, 0x94562d44, 0x4a71f54),
    'first_item_saved_for_constructor': ('PlayerProfile.PopCarIfInDeliveryWaitingList', 0x34e6a50, 0x2a0003f5, None),
    'second_list_reloaded': ('PlayerProfile.PopCarIfInDeliveryWaitingList', 0x34e6a54, 0xf943a500, None),
    'second_item_uses_position_zero': ('PlayerProfile.PopCarIfInDeliveryWaitingList', 0x34e6a60, 0x2a1f03e1, None),
    'second_list_position_zero_read': ('PlayerProfile.PopCarIfInDeliveryWaitingList', 0x34e6a64, 0x94562d3c, 0x4a71f54),
    'second_item_into_second_word': ('PlayerProfile.PopCarIfInDeliveryWaitingList', 0x34e6a6c, 0x2a0003e2, None),
    'first_item_into_first_word': ('PlayerProfile.PopCarIfInDeliveryWaitingList', 0x34e6a74, 0x2a1503e1, None),
    'construct_success_pair': ('PlayerProfile.PopCarIfInDeliveryWaitingList', 0x34e6a7c, 0x9453254d, 0x49affb0),
    'first_list_for_removal': ('PlayerProfile.PopCarIfInDeliveryWaitingList', 0x34e6a88, 0xf943a100, None),
    'first_remove_uses_computed_index': ('PlayerProfile.PopCarIfInDeliveryWaitingList', 0x34e6a98, 0x2a1403e1, None),
    'first_list_remove': ('PlayerProfile.PopCarIfInDeliveryWaitingList', 0x34e6aa0, 0x945633f9, 0x4a73a84),
    'second_list_for_removal': ('PlayerProfile.PopCarIfInDeliveryWaitingList', 0x34e6aac, 0xf943a500, None),
    'second_remove_uses_computed_index': ('PlayerProfile.PopCarIfInDeliveryWaitingList', 0x34e6ab8, 0x2a1403e1, None),
    'second_list_remove': ('PlayerProfile.PopCarIfInDeliveryWaitingList', 0x34e6abc, 0x945633f2, 0x4a73a84),
    'success_skips_sentinel': ('PlayerProfile.PopCarIfInDeliveryWaitingList', 0x34e6ac0, 0x14000007, None),
    'sentinel_first_word_negative_one': ('PlayerProfile.PopCarIfInDeliveryWaitingList', 0x34e6acc, 0x12800001, None),
    'sentinel_second_word_negative_one': ('PlayerProfile.PopCarIfInDeliveryWaitingList', 0x34e6ad0, 0x12800002, None),
    'construct_sentinel_pair': ('PlayerProfile.PopCarIfInDeliveryWaitingList', 0x34e6ad8, 0x94532536, 0x49affb0),
    'load_packed_return': ('PlayerProfile.PopCarIfInDeliveryWaitingList', 0x34e6adc, 0xf94007e0, None),
    'return': ('PlayerProfile.PopCarIfInDeliveryWaitingList', 0x34e6af0, 0xd65f03c0, None),
    'constructor_stores_two_words': ('delivery_pair_constructor', 0x49affb0, 0x29000801, None),
    'constructor_returns': ('delivery_pair_constructor', 0x49affb4, 0xd65f03c0, None),
}

_BRANCH_EDGES = {
    'first_list_empty_to_sentinel': (0x34e6ac4, 0x34e69c8),
    'second_list_empty_to_sentinel': (0x34e6ac4, 0x34e69d8),
    'computed_negative_index_to_sentinel': (0x34e6ac4, 0x34e6a20),
    'success_skips_sentinel': (0x34e6adc,),
}


def _s32(word: int) -> int:
    word &= 0xffffffff
    return word - (1 << 32) if word >= (1 << 31) else word


def model_pair_lists(first: Sequence[int], second: Sequence[int], *, computed_index: int | None) -> dict[str, Any]:
    """Synthetic normal-path model. Does not emulate lookup or null exceptions.

    On a successful lookup, each return value is read from position zero while
    each corresponding removal uses computed_index, which can be nonzero.
    """
    a, b = tuple(first), tuple(second)
    if len(a) > 1000 or len(b) > 1000 or any(not isinstance(x, int) or x < -(1 << 31) or x >= (1 << 31) for x in (*a, *b)):
        raise ValueError('invalid synthetic list values')
    if computed_index is not None and (not isinstance(computed_index, int) or computed_index < -0x80000000 or computed_index > 0x7fffffff):
        raise ValueError('invalid synthetic lookup index')
    if not a or not b or computed_index is None or computed_index < 0:
        low, high = -1, -1
        remaining_a, remaining_b = a, b
        result = 'sentinel'
    else:
        if computed_index >= len(a) or computed_index >= len(b):
            raise ValueError('synthetic removal index outside list; exception paths not modeled')
        low, high = a[0], b[0]
        remaining_a = a[:computed_index] + a[computed_index + 1:]
        remaining_b = b[:computed_index] + b[computed_index + 1:]
        result = 'paired_read_and_remove'
    packed = ((high & 0xffffffff) << 32) | (low & 0xffffffff)
    return {
        'result_path': result,
        'low_word_signed': low,
        'high_word_signed': high,
        'packed_u64_hex': f'0x{packed:016x}',
        'dev75_positive_pop_gate': _s32(low) > 0,
        'return_reads_both_lists_at_position_zero_on_success': result == 'paired_read_and_remove',
        'remove_index': computed_index if result == 'paired_read_and_remove' else None,
        'first_list_after': list(remaining_a),
        'second_list_after': list(remaining_b),
        'synthetic_only': True,
    }


def audit_native(metadata: bytes, native: bytes) -> dict[str, Any]:
    previous = audit_dev75(metadata, native)
    if previous['production_mappings_changed'] or previous['runtime_ordered_paint_list_captured']:
        raise ValueError('previous static-only guarantees changed')
    if previous['managed_method_pointers'].get('PlayerProfile.PopCarIfInDeliveryWaitingList') != hex(_NATIVE_SPANS['PlayerProfile.PopCarIfInDeliveryWaitingList'][0]):
        raise ValueError('delivery method metadata pointer changed')
    elf = _ELF(native)
    bodies: dict[str, bytes] = {}
    for name, (base, length, expected_hash) in _NATIVE_SPANS.items():
        if length % 4 or not 0 < length <= 8192:
            raise ValueError('invalid native span length')
        body = _slice(native, elf.fileoff(base, length, execute=True), length)
        if hashlib.sha256(body).hexdigest() != expected_hash:
            raise ValueError('delivery native fingerprint changed: ' + name)
        bodies[name] = body
    pinned = {}
    for label, (owner, rva, expected, direct) in _SITES.items():
        base, length, _ = _NATIVE_SPANS[owner]
        if not base <= rva < base + length or (rva - base) % 4:
            raise ValueError('native site outside bounded method')
        got = struct.unpack_from('<I', bodies[owner], rva - base)[0]
        if got != expected:
            raise ValueError('delivery instruction changed: ' + label)
        if direct is not None and _decode_bl(got, rva) != direct:
            raise ValueError('delivery direct-call target changed: ' + label)
        pinned[label] = {'rva': hex(rva), 'word': hex(got)}
        if direct is not None:
            pinned[label]['direct_target'] = hex(direct)
    for label, expected in _BRANCH_EDGES.items():
        _, pc, word, _ = _SITES[label]
        if _successors(pc, word) != expected:
            raise ValueError('delivery branch edge changed: ' + label)
    return {
        'status': 'dev76_delivery_tuple_index_provenance_static',
        'client': 'CSR2 6.8.0',
        'source': {'enum': 'Tutorial', 'value': 1, 'direct_source_check_in_pop_method_verified': False},
        'native_spans': {key:{'rva':hex(base),'bounded_length':length,'sha256':digest}
                         for key,(base,length,digest) in sorted(_NATIVE_SPANS.items())},
        'previous_dev75_metadata_pointer_preserved': True,
        'previous_dev72_75_static_guard_chain_passed': True,
        'pinned_instructions': pinned,
        'branch_edges': {key:[hex(x) for x in value] for key,value in sorted(_BRANCH_EDGES.items())},
        'delivery_result': {
            'first_list_profile_field': '+0x740', 'second_list_profile_field': '+0x748',
            'first_and_second_list_count_checked_nonzero': True,
            'precomputed_lookup_index_negative_routes_to_sentinel': True,
            'return_reads_first_list_position': 0,
            'return_reads_second_list_position': 0,
            'first_list_removal_uses_precomputed_index': True,
            'second_list_removal_uses_precomputed_index': True,
            'computed_removal_index_guaranteed_to_equal_return_read_index_zero': False,
            'pair_constructor_at': '0x49affb0',
            'low_word_list_field': '+0x740', 'high_word_list_field': '+0x748',
            'no_entry_sentinel_pair': [-1,-1],
            'missing_lists_null_exception_cases_modeled': False,
            'pop_method_may_consume_profile_list_entries': True,
            'recommended_runtime_observation': 'read-only snapshot of relevant state, not replaying the destructive pop method',
        },
        'synthetic_scenarios_not_runtime_observations': {
            'empty_first_list': model_pair_lists([], [3], computed_index=0),
            'missing_lookup': model_pair_lists([111], [2], computed_index=-1),
            'successful_index_zero': model_pair_lists([111], [2], computed_index=0),
            'computed_index_differs_from_return_read_position': model_pair_lists([111,222], [2,7], computed_index=1),
            'nonpositive_first_value': model_pair_lists([0], [2], computed_index=0),
        },
        'actual_list_state_observed': False,
        'actual_delivery_result_observed': False,
        'actual_gacha_branch_outcome_observed': False,
        'runtime_ordered_paint_list_captured': False,
        'production_paint_mapping_verified': False,
        'paint_index_15_conditional_candidate': 1323,
        'paint_index_0': 'unresolved',
        'production_mappings_changed': False,
        'network_requests': 0, 'gameplay_reads': 0,
        'private_roster_read': False,
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
        body = json.dumps(report, sort_keys=True, indent=2) + '\n'
        if len(body.encode('utf-8')) > 150_000:
            raise ValueError('oversized evidence output')
        with args.output.open('x', encoding='utf-8') as stream:
            stream.write(body)
    except (OSError, ValueError, KeyError, struct.error) as error:
        parser.error(str(error))
    print('Dev76: delivery pop reads first list entries, removal uses computed index; runtime state unknown.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
