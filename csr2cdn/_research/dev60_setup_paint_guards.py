"""Dev60: pinned native audit of pre-unlockable paint list mutation in CarVisuals.Setup.

Offline, evidence-graded investigation only. Different configuration branches can
append a garage-visual paint ID BEFORE CarVisuals.ForceUpdateOfCarPaint uses the
restoration unlockables. The presence of a branch does NOT establish its runtime
execution for the affected car, nor establish a roster paint label.

Inputs stay on the operator's computer. Output contains only vehicle-source
aggregates, safe paint IDs, and compiled method fingerprints; no roster data.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct
from typing import Any

from .dev48_native_paint_methods import _ELF, _slice
from .dev58_runtime_paint_replay import _TARGETS, _verify_instruction, conditional_list, _catalogue_label
from .dev59_milestone_unlockables import _read_native, audit_native, inspect as dev59_inspect
from .dev57_unity_carvisuals import parse_asset, unpack_unityfs

_SETUP = ('CarVisuals', 'Setup')
# Addresses and 32-bit AArch64 opcodes pinned to the exact 6.8.0 client binary.
_SITES: dict[str, tuple[int, int]] = {
    'car_source_field_read': (0x38029a4, 0xb9410808),
    'special_car_source_bitmask': (0x38029b8, 0x5280c08a),
    'car_source_branch': (0x38029c0, 0x54000e60),
    'current_paint_index_early_read': (0x38029c4, 0xb9411e68),
    'negative_index_skips_first_candidate': (0x38029c8, 0x37f80748),
    'garage_visual_reference_read': (0x38029cc, 0xf940b408),
    'garage_visual_paint_id_read': (0x38029d4, 0xb9401d08),
    'visual_paint_sentinel': (0x38029d8, 0x12b00009),
    'visual_paint_sentinel_cmp': (0x38029dc, 0x6b09011f),
    'paint_id_already_present_compare': (0x3802a48, 0x3100041f),
    'first_preappend_write': (0x3802aa8, 0xb9002101),
    'fallback_visual_id_read': (0x3803060, 0xb9401d21),
    'fallback_preappend_write': (0x380309c, 0xb9002121),
    'garage_selected_index_late_read': (0x3803680, 0xb9406d08),
    'car_visuals_selected_index_store': (0x380369c, 0xb9011e68),
    'force_update_call': (0x38036a0, 0x94001f96),
    'fallback_correction_selected_index_read': (0x38036f4, 0xb9406d09),
    'fallback_correction_count_read': (0x3803704, 0xb9401929),
    'fallback_correction_selected_index_store': (0x380370c, 0xb9006d09),
}


def audit_setup(meta: bytes, native: bytes) -> dict[str, Any]:
    # Verify every pinned class/method/branch from Dev59 first (includes APK SHA pin).
    previous = audit_native(meta, native)
    elf = _ELF(native)
    addr, length, digest = _TARGETS[_SETUP]
    code = _slice(native, elf.fileoff(addr, length, execute=True), length)
    if hashlib.sha256(code).hexdigest() != digest:
        raise ValueError('CarVisuals.Setup native fingerprint mismatch')
    for _, (site, instruction) in _SITES.items():
        _verify_instruction(code, addr, site, instruction)
    return {
        'method': {'class':'CarVisuals','method':'Setup','rva':hex(addr),'sha256':digest},
        'checked_instruction_sites': {key:hex(address) for key,(address,_) in _SITES.items()},
        'pre_unlocked_append_is_conditional': True,
        'source_branch_mask': '0x604',
        'source_branch_raw_enum_values':[2,9,10],
        'source_field_at_garage_car':'0x108',
        'garage_visual_object_offset':'0x168',
        'garage_visual_paint_id_field_offset':'0x1c',
        'early_current_paint_index_field_offset':'0x11c',
        'later_garage_selected_index_field_offset':'0x6c',
        'first_preappend_site':'0x3802aa8',
        'fallback_preappend_site':'0x380309c',
        'force_update_called_after_preappend':'0x38036a0',
        'fallback_can_change_garage_selected_index':True,
        'locked_unlockables_getall_sha256': previous['methods']['LockedCustomisationData.GetAllUnlockables']['sha256'],
        'source_enum_meaning_verified':False,
        'branch_taken_for_roster_car_verified':False,
    }


def replay_single_preappend(base: list[int], unlockables: list[int], index: int, preappend: int | None) -> dict[str, Any]:
    """Conditional what-if only: one preappend in the observed source order."""
    if type(index) is not int or not 0 <= index < 2048:
        raise ValueError('invalid paint index')
    if preappend is not None and (type(preappend) is not int or preappend < 0 or preappend > 0x7ffffffe):
        raise ValueError('invalid preappend paint ID')
    start = base.copy()
    added = False
    if preappend is not None and preappend not in start:
        start.append(preappend)
        added = True
    combined, appended = conditional_list(start, unlockables)
    return {
        'initial_early_append_happened': added,
        'selected_paint_id': combined[index] if index < len(combined) else None,
        'combined_count': len(combined),
        'aftermarket_new_count': len(appended),
    }


def inspect(apk:Path, bundle:Path, catalog:Path | None=None, paint_index:int=15)->dict[str,Any]:
    prior = dev59_inspect(apk,bundle,catalog,paint_index)
    meta,native = _read_native(apk)
    checked = audit_setup(meta,native)
    visual, locked = parse_asset(unpack_unityfs(bundle.read_bytes()))
    base=visual['CarPaintIDs']; raw=locked['AllUnlockables']['carPaintIDs']
    baseline = replay_single_preappend(base,raw,paint_index,None)
    if baseline['selected_paint_id'] != prior['static_replay']['candidate_at_received_index']:
        raise ValueError('Dev59 baseline regression')
    # These IDs are from this exact decoded bundle, not fabricated runtime data.
    plausible = sorted(set(x for x in raw if x >= 0) | set(c['PaintID'] for c in visual['GachaConfigs']))
    if len(plausible)>1000:
        raise ValueError('too many variant source candidates')
    variants=[]
    for paint_id in plausible:
        result = replay_single_preappend(base,raw,paint_index,paint_id)
        variants.append({'source_paint_id':paint_id,
                         'early_added':result['initial_early_append_happened'],
                         'selected_paint_id':result['selected_paint_id']})
    # An arbitrary *non-catalogue* novel ID only illustrates the effect of
    # adding an unanticipated paint before restoration IDs. Never call it a game value.
    dummy = 424242
    if dummy in base or dummy in raw or dummy in plausible:
        raise ValueError('illustrative distinct placeholder collided')
    novel = replay_single_preappend(base,raw,paint_index,dummy)
    outcomes=sorted(set([baseline['selected_paint_id'], novel['selected_paint_id']]+[x['selected_paint_id'] for x in variants]) - {None})
    candidates=[]
    for value in outcomes:
        label, source = _catalogue_label(catalog,value)
        candidates.append({'paint_id':value,'library_label':label,'library':source,
                           'scenario_only':True})
    return {
        'status':'dev60_conditional_pre_unlockables_paint_append_discovered',
        'native_setup':checked,
        'paint_index':paint_index,
        'bundle_sha256':prior['bundle_sha256'],
        'base_count':len(base),
        'serialized_unlockable_entries':len(raw),
        'baseline_without_preappend':baseline,
        'one_preappend_variants_from_bundle':variants,
        'hypothetical_other_distinct_id':{
            'description':'An otherwise-unseen distinct paint ID; dummy value not a claimed asset',
            'selected_paint_id':novel['selected_paint_id']},
        'possible_labels_under_tested_one_preappend_scenarios':candidates,
        'scenario_limit':'Only zero or one earlier append. Multiple or other runtime mutations could yield other results.',
        'runtime_car_source_confirmed':False,
        'runtime_original_garage_visual_paint_id_confirmed':False,
        'runtime_crew_paint_label_confirmed':False,
        'production_mapping_changed':False,
        'reads_private_roster':False,
        'network_calls':0,
    }


def main(argv:list[str] | None=None)->int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--apk',required=True,type=Path)
    p.add_argument('--bundle',required=True,type=Path)
    p.add_argument('--source-catalog',type=Path)
    p.add_argument('--paint-index',type=int,default=15)
    p.add_argument('--output',required=True,type=Path)
    a=p.parse_args(argv)
    if a.output.exists() or a.output.is_symlink(): p.error('refusing to overwrite an existing report')
    try:
        report=inspect(a.apk,a.bundle,a.source_catalog,a.paint_index)
        output=json.dumps(report,indent=2,sort_keys=True)+'\n'
        if len(output.encode('utf8'))>200000:raise ValueError('output too large')
        a.output.write_text(output,encoding='utf8')
    except (ValueError,KeyError,IndexError,OSError,struct.error) as e:p.error(str(e))
    print('Dev60: conditional pre-unlockables paint append audited; roster paint label unverified.')
    return 0

if __name__=='__main__':raise SystemExit(main())
