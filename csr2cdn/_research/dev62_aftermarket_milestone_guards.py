"""Dev62: fail-closed, offline trace of CSR2 6.8.0 restoration setup guards.

The cached crew milestone level is a wire observation, NOT proof that level
alters the order of the serialized AllUnlockables.carPaintIDs list. This tool
checks the exact setup branches and native field writes against the operator's
APK and validates conditional replay of their provided Unity bundle. It makes
no server requests, exports no roster identities, and changes no mappings.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct
from typing import Any

from .dev48_native_paint_methods import _ELF, _slice
from .dev54_initial_paint_setup import _decode_bl
from .dev58_runtime_paint_replay import _TARGETS as VISUAL_METHODS, _verify_instruction
from .dev59_milestone_unlockables import _TARGETS as LOCKED_METHODS, _read_native, audit_native
from .dev61_source_enum_guard import inspect as dev61_inspect

_SETUP=('CarVisuals','Setup')
_AFTER=('CarVisuals','SetupAftermarketLockedData')
_PREP=('LockedCustomisationData','SetupMilestones')
_GETALL=('LockedCustomisationData','GetAllUnlockables')
_ARE=('LockedCustomisationData','get_AreMilestonesSetup')
# Pinned native ARM64 bytes are only valid for this exact fingerprinted APK.
_OPCODES={
    'garage_has_milestones_call':(_SETUP,0x38035d0,0x97f1cd10),
    'skip_setup_if_no_milestones':(_SETUP,0x38035d4,0x36000120),
    'garage_is_tuner_stars_call':(_SETUP,0x38035e4,0x97f1cb60),
    'skip_setup_if_tuner_stars':(_SETUP,0x38035e8,0x37000080),
    'call_setup_aftermarket':(_SETUP,0x38035f4,0x94002701),
    'record_garage_object_on_helper':(_AFTER,0x380d3f0,0xf9000a95),
    'query_milestones_already_setup':(_AFTER,0x380d448,0x94006972),
    'branch_on_are_setup':(_AFTER,0x380d44c,0x36000560),
    'pass_saved_garage_into_milestone_setup':(_AFTER,0x380dd10,0xf9400a81),
    'pass_locked_data_object_into_milestone_setup':(_AFTER,0x380dd14,0xaa1503e0),
    'call_setup_milestones':(_AFTER,0x380dd1c,0x94006837),
    'milestone_serialized_source_list_read':(_PREP,0x3827e50,0xf9401295),
    'milestone_prepared_list_write':(_PREP,0x3827e88,0xf9001a96),
    'existing_all_unlockables_cache_load':(_GETALL,0x3828074,0xf94016a0),
    'non_null_all_unlockables_fast_path':(_GETALL,0x3828078,0xb5001380),
}
_METHODS={_SETUP:VISUAL_METHODS[_SETUP],**{key:LOCKED_METHODS[key] for key in (_AFTER,_PREP,_GETALL,_ARE)}}
# Existing method RVA proofs: HasMilestonesForCar / IsTunerStarsCar
_CALL_TARGETS={
    'garage_has_milestones_call':0x3476a10,
    'garage_is_tuner_stars_call':0x3476364,
    'call_setup_aftermarket':LOCKED_METHODS[_AFTER][0],
    'query_milestones_already_setup':LOCKED_METHODS[_ARE][0],
    'call_setup_milestones':LOCKED_METHODS[_PREP][0],
}


def audit_restoration_setup(meta: bytes,native: bytes)->dict[str,Any]:
    """Verify exact callsites and fields; never infer runtime branch outcomes."""
    # Checks APK fingerprint, code-generation method-pointer table, full method
    # bodies, and the GetAllUnlockables direct-return branch before reuse.
    previous=audit_native(meta,native)
    elf=_ELF(native)
    bodies={}
    for key,(rva,length,digest) in _METHODS.items():
        body=_slice(native,elf.fileoff(rva,length,execute=True),length)
        if hashlib.sha256(body).hexdigest()!=digest:
            raise ValueError(f'Unexpected native method fingerprint for {key}')
        bodies[key]=body
    checked={}
    for name,(key,addr,opcode) in _OPCODES.items():
        _verify_instruction(bodies[key],_METHODS[key][0],addr,opcode)
        if name in _CALL_TARGETS and _decode_bl(opcode,addr)!=_CALL_TARGETS[name]:
            raise ValueError(f'Unexpected native branch target: {name}')
        checked[name]=hex(addr)
    return {
        'apk': 'CSR2 6.8.0 (exact metadata and ARM64 native body fingerprints)',
        'verified_method_fingerprints':{
            '.'.join(k):{'rva':hex(v[0]),'sha256':v[2]} for k,v in sorted(_METHODS.items())
        },
        'verified_instruction_sites':checked,
        'setup_path':{
            'garage_has_milestones_call':hex(_CALL_TARGETS['garage_has_milestones_call']),
            'garage_is_tuner_stars_call':hex(_CALL_TARGETS['garage_is_tuner_stars_call']),
            'calls_locked_data_setup_only_if_has_milestones_and_not_tuner_stars':True,
            'runtime_predicates_observed':False,
        },
        'locked_data_path':{
            'setup_receives_saved_garage_object':True,
            'already_prepared_milestones_checked':True,
            'serialized_source_milestone_list_offset':'0x20',
            'prepared_milestone_list_written_offset':'0x30',
            'serialized_or_cached_all_unlockables_offset':'0x28',
            'get_all_unlockables_returns_existing_non_null_field_directly':True,
            'milestone_setup_writes_all_unlockables_field_directly':False,
            'runtime_all_unlockables_identity_preserved_verified':False,
            'milestone_level_50_reorders_all_unlockables_verified':False,
        },
        'prior_apk_getall_cache_evidence':previous['native_cache_branch'],
    }


def branch_outcome(*,has_milestones:bool|None,is_tuner_stars:bool|None)->str:
    """Logic reproduced from two verified setup guards, not measured booleans."""
    if (type(has_milestones) not in (bool,type(None)) or
            type(is_tuner_stars) not in (bool,type(None))):
        raise ValueError('invalid milestone/tuner stars predicate')
    if has_milestones is False:return 'setup_aftermarket_locked_data_skipped_no_milestones'
    if has_milestones is True and is_tuner_stars is True:
        return 'setup_aftermarket_locked_data_skipped_tuner_stars'
    if has_milestones is True and is_tuner_stars is False:
        return 'setup_aftermarket_locked_data_called'
    return 'not_determined_without_runtime_predicates'


def inspect(apk:Path,bundle:Path,catalog:Path|None=None,*,cache:Path|None=None,
            vehicle:str='Ford_Mustang302_1970',paint_index:int=15)->dict[str,Any]:
    prior=dev61_inspect(apk,bundle,catalog,cache=cache,vehicle=vehicle,paint_index=paint_index)
    meta,native=_read_native(apk)
    native_evidence=audit_restoration_setup(meta,native)
    roster=prior['vehicle_source_evidence']
    baseline=prior['without_early_append']
    return {
        'status':'dev62_pinned_aftermarket_setup_guards_and_unlockables_cache_trace',
        'apk_native':native_evidence,
        'input_roster_evidence_redacted':roster,
        'source_guard_classification':prior['source_guard_classification'],
        'observed_cached_milestone_level':roster['aftermarket_milestone_level'] if roster else None,
        'milestone_level_used_as_index_or_list_order_modifier_verified':False,
        'runtime_has_milestones_predicate_verified':False,
        'runtime_is_tuner_stars_predicate_verified':False,
        'predicate_outcomes':{
            'when_true_false':branch_outcome(has_milestones=True,is_tuner_stars=False),
            'when_false_unknown':branch_outcome(has_milestones=False,is_tuner_stars=None),
            'when_true_true':branch_outcome(has_milestones=True,is_tuner_stars=True),
        },
        'static_bundle_replay_without_early_append':{
            'paint_index':paint_index,
            'candidate_paint_id':baseline['conditional_paint_id'],
            'candidate_library_label':baseline['conditional_label'],
            'total_paint_ids':baseline['ordered_list_count'],
            'applies_only_if_actual_runtime_uses_bundle_unmodified_and_setup_expands_list':True,
        },
        'remaining_runtime_gaps':[
            'HasMilestonesForCar and IsTunerStarsCar return values were not observed on this crew garage object.',
            'The saved restoration milestone number alone does not reveal the runtime method return values.',
            'The locked customisation data may be replaced, modified, or its cache reset by other runtime paths.',
            'No captured runtime paint list, selected renderer paint ID, or production paint mapping exists.',
        ],
        'paint_index_0_verified':False,'paint_index_15_verified':False,
        'network_requests':0,'authenticated_reads':0,'production_mapping_changed':False,
        'private_roster_exported':False,
    }


def main(argv:list[str]|None=None)->int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--apk',type=Path,required=True)
    p.add_argument('--bundle',type=Path,required=True)
    p.add_argument('--source-catalog',type=Path)
    p.add_argument('--private-cache-zip',type=Path)
    p.add_argument('--vehicle',default='Ford_Mustang302_1970')
    p.add_argument('--paint-index',type=int,default=15)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args(argv)
    if a.output.exists() or a.output.is_symlink():p.error('Refusing to overwrite an existing report')
    result=inspect(a.apk,a.bundle,a.source_catalog,cache=a.private_cache_zip,
                   vehicle=a.vehicle,paint_index=a.paint_index)
    a.output.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    return 0


if __name__=='__main__':
    raise SystemExit(main())
