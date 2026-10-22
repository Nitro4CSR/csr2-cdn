"""Dev67: offline, SHA-256-pinned native configuration load & late paint insertion audit.

Verifies selected CSR2 6.8.0 ARM64 methods and instruction callsites. The
current CarMetadata / visual bundle and official public cached scheme are
independently joined using Dev66. Nothing here claims live manager state,
paint array contents, or actual renderer output. Never performs network reads
or modifies production cosmetic resolution. Original APK/bundles/cache are
operator-owned inputs, not distributed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct
from typing import Any

from .dev48_native_paint_methods import _ELF, _slice
from .dev59_milestone_unlockables import _read_native
from .dev66_carinfo_paint_join import inspect as inspect_current_assets
from .dev63_garage_milestone_predicates import _branch

# Exact native bodies from the operator-provided CSR2 6.8.0 ARM64 library.
_NATIVE_METHODS = {
    'CarMilestoneDataManager.LoadDataFromJsonDict':(
        0x2e28968,344,'a57103e6f845e108f2eee7cb0d90c75192694b58a8de5159ca6fd5d637f109ea'),
    'CarMilestoneDataManager.OnConfigLoadedFromJson':(
        0x2e29a6c,16,'c29c6c08bc8c3219cd7720f84e815166771bb91829c8b5549c14c065ad3e2a22'),
    'CarMilestoneDataManager.OnConfigLoadedFromBinary':(
        0x2e29a7c,36,'750e9a2cdafc4bf36313718132eef09e6e7260ddf28320bcfe170089f271e2dd'),
    'CarLoader.SetupCarVisuals':(
        0x2eb7df4,1648,'328f3655c0499245829708a8317790e3069359069f15f2f13c10af1e6cd482b6'),
    'RaceStateSetupHumanCarHelper.HumanSetupCarVisuals':(
        0x35bb8bc,1436,'bce47b38c0de5ddb042d97cd40e5b5d737e1386e20ca35076a50e94ec74315e5'),
    'RaceStateSetupAICarHelper.AiSetupCarVisuals':(
        0x35c0380,3648,'e64e8e45b01696e012cd7547e19a6c230fdd9e7928e1bd28737ff558e8d88586'),
}
# Each checked instruction belongs to the corresponding fingerprinted body.
# For B/BL also check the computed *exact* target, not only the opcode.
_INSTRUCTIONS = {
    'json_scheme_parse_call_first':(
        'CarMilestoneDataManager.LoadDataFromJsonDict',0x2e28a20,0x94000028,0x2e28ac0),
    'json_scheme_parse_call_second':(
        'CarMilestoneDataManager.LoadDataFromJsonDict',0x2e28a94,0x9400000b,0x2e28ac0),
    'on_json_loaded_calls_json_parser':(
        'CarMilestoneDataManager.OnConfigLoadedFromJson',0x2e29a74,0x17fff98b,0x2e280a0),
    'on_binary_loaded_calls_binary_parser':(
        'CarMilestoneDataManager.OnConfigLoadedFromBinary',0x2e29a88,0x97fff718,0x2e276e8),
    'car_loader_sentinel_constant':(
        'CarLoader.SetupCarVisuals',0x2eb8110,0x12b00008,None),
    'car_loader_compares_sentinel':(
        'CarLoader.SetupCarVisuals',0x2eb8114,0x6b08003f,None),
    'car_loader_sentinel_branch':(
        'CarLoader.SetupCarVisuals',0x2eb8118,0x54000161,None),
    'car_loader_insert_paint_id':(
        'CarLoader.SetupCarVisuals',0x2eb814c,0x94256f26,0x3813de4),
    'car_loader_get_selected_index':(
        'CarLoader.SetupCarVisuals',0x2eb8154,0xb9411ea8,None),
    'car_loader_copy_selected_index_to_garage':(
        'CarLoader.SetupCarVisuals',0x2eb8158,0xb9006e88,None),
    'human_race_custom_paint_insert':(
        'RaceStateSetupHumanCarHelper.HumanSetupCarVisuals',0x35bbc0c,0x94096076,0x3813de4),
    'human_race_paint_zero_argument':(
        'RaceStateSetupHumanCarHelper.HumanSetupCarVisuals',0x35bbdfc,0x2a1f03e1,None),
    'human_race_paint_zero_insert':(
        'RaceStateSetupHumanCarHelper.HumanSetupCarVisuals',0x35bbe04,0x94095ff8,0x3813de4),
    'ai_race_selected_paint_argument':(
        'RaceStateSetupAICarHelper.AiSetupCarVisuals',0x35c0f2c,0x2a1d03e1,None),
    'ai_race_custom_paint_insert':(
        'RaceStateSetupAICarHelper.AiSetupCarVisuals',0x35c0f38,0x94094bab,0x3813de4),
}


def audit_native(meta:bytes, native:bytes) -> dict[str,Any]:
    """Verify observed native callsites with exact fingerprinted method bodies.

    Metadata/APK version pinning is inherited through `_read_native` for APK
    inputs; here the checked method body fingerprints and addresses fail closed.
    """
    if not isinstance(meta,bytes) or len(meta)<128:
        raise ValueError('missing compiled metadata')
    elf=_ELF(native)
    bodies={}
    for name,(rva,size,expected_sha) in _NATIVE_METHODS.items():
        if not 4<=size<=8192 or rva%4 or size%4:
            raise ValueError('invalid pinned native method span')
        body=_slice(native,elf.fileoff(rva,size,execute=True),size)
        if hashlib.sha256(body).hexdigest()!=expected_sha:
            raise ValueError('native method fingerprint mismatch: '+name)
        bodies[name]=body
    sites={}
    for label,(name,at,word,target) in _INSTRUCTIONS.items():
        rva,size,_=_NATIVE_METHODS[name]
        if at<rva or at+4>rva+size:
            raise ValueError('native instruction outside method: '+label)
        observed=struct.unpack_from('<I',bodies[name],at-rva)[0]
        if observed!=word:
            raise ValueError('changed native instruction: '+label)
        if target is not None and _branch(observed,at)!=target:
            raise ValueError('changed native direct call/branch target: '+label)
        sites[label]={'address':hex(at),'opcode':hex(observed)}
        if target is not None:sites[label]['target']=hex(target)
    return {
        'methods':{name:{'rva':hex(rva),'body_length':size,'sha256':digest}
                   for name,(rva,size,digest) in _NATIVE_METHODS.items()},
        'verified_sites':sites,
        'verified_milestone_manager_load_routes':{
            'json_callback_delegates_to_json_parser':True,
            'binary_callback_calls_binary_parser':True,
            'json_dictionary_parser_calls_LoadSchemeFromDict_twice':True,
            'loaded_EliteCustoms_FTUECar_membership_observed':False,
        },
        'verified_later_paint_mutation_paths':{
            'CarLoader_SetupCarVisuals_inserts_paint_id_when_non_sentinel':True,
            'CarLoader_copies_CurrentPaintIndex_to_garage_selected_index':True,
            'HumanRaceSetup_calls_paint_insertion_twice':True,
            'HumanRaceSetup_has_literal_zero_as_one_paint_insertion_argument':True,
            'AIRaceSetup_calls_paint_insertion':True,
            'these_paths_shown_to_run_for_cached_crew_car':False,
        },
        'native_runtime_paint_list_captured':False,
    }


def inspect(apk:Path,car_metadata_bundle:Path,visual_bundle:Path,
            cache_zip:Path,source_catalog:Path,
            *,vehicle:str='Ford_Mustang302_1970',paint_index:int=15)->dict[str,Any]:
    meta,native=_read_native(apk)
    native_report=audit_native(meta,native)
    previous=inspect_current_assets(car_metadata_bundle,visual_bundle,cache_zip,
                                    apk,source_catalog,vehicle,paint_index)
    carinfo=previous['current_carinfo']
    replay=previous['conditional_paint_replay']
    scheme=previous['verified_public_milestone_scheme']
    return {
        'status':'dev67_milestone_config_routes_and_later_paint_mutation_traced',
        'apk_native':native_report,
        'car_key':vehicle,
        'source_database_version':'34011',
        'current_carinfo':{
            'bundle_sha256':carinfo['bundle_sha256'],
            'is_tuner_stars_car':carinfo['carinfo']['is_tuner_stars_car'],
            'record_decoded_from_current_asset':True,
            'heap_record_loaded_value_observed':False,
        },
        'public_milestone_scheme':{
            'scheme_id':scheme['pricing_scheme_id'],
            'defined_milestone_count':scheme['defined_milestone_count'],
            'ftue_vehicle_config_matches':scheme['configured_ftue_car_matches'],
            'scheme_present_in_public_metadata':True,
            'scheme_present_in_live_loaded_manager':False,
        },
        'paint_reconstruction':{
            'received_index':replay['paint_index'],
            'candidate_paint_id':replay['paint_id'],
            'candidate_label':replay['library_label'],
            'reconstructed_list_count':replay['combined_list_length'],
            'runtime_list_captured':False,
            'rendered_paint_id_observed':False,
            'candidate_only':True,
        },
        'scene_specific_path_executed_for_crew_vehicle':False,
        'human_race_zero_argument_proves_roster_zero_semantics':False,
        'paint_index_zero_meaning':'unresolved',
        'production_paint_mapping_changed':False,
        'network_requests':0,'authenticated_gameplay_reads':0,'player_identifiers_exported':False,
    }


def main(argv:list[str]|None=None)->int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apk',type=Path,required=True)
    parser.add_argument('--car-metadata-bundle',type=Path,required=True)
    parser.add_argument('--visual-bundle',type=Path,required=True)
    parser.add_argument('--cache-zip',type=Path,required=True)
    parser.add_argument('--source-catalog',type=Path,required=True)
    parser.add_argument('--vehicle',default='Ford_Mustang302_1970')
    parser.add_argument('--paint-index',type=int,default=15)
    parser.add_argument('--output',type=Path,required=True)
    a=parser.parse_args(argv)
    if a.output.exists() or a.output.is_symlink():
        parser.error('refusing to overwrite an existing report')
    report=inspect(a.apk,a.car_metadata_bundle,a.visual_bundle,a.cache_zip,
                   a.source_catalog,vehicle=a.vehicle,paint_index=a.paint_index)
    a.output.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n',encoding='utf8')
    return 0

if __name__=='__main__':
    raise SystemExit(main())
