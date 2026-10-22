"""Join public, offline current CarInfo flag with the conditional car paint replay.

The current CarMetadata bundle resolves `IsTunerStarsCar` in *serialized*
CarInfo. It does not capture the live CarDatabase or car paint array. The
existing Dev58 native-backed list replay therefore remains conditional.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from typing import Any

from .dev66_carinfo_decoder import inspect as inspect_car_metadata, CarMetadataError
from .dev57_unity_carvisuals import parse_asset, unpack_unityfs
from .dev58_runtime_paint_replay import conditional_list
from .dev63_garage_milestone_predicates import inspect_public_schemes
from .dev59_milestone_unlockables import _read_native
from .dev65_carinfo_bundle_target import native_provenance, indexed_candidate


def inspect(car_metadata:Path, visual_bundle:Path|None=None,
            cache_zip:Path|None=None, apk:Path|None=None,
            source_catalog:Path|None=None,
            vehicle:str='Ford_Mustang302_1970', paint_index:int=15)->dict[str,Any]:
    current=inspect_car_metadata(car_metadata,vehicle)
    result={'status':'dev66_current_carinfo_tuner_flag_decoded',
        'current_carinfo':current,
        'record_is_tuner_stars_car':current['carinfo']['is_tuner_stars_car'],
        'native_tuner_stars_guard_excluded_by_record':current['carinfo']['is_tuner_stars_car'] is False,
        'runtime_car_database_return_captured':False,
        'runtime_paint_list_captured':False,
        'authenticated_gameplay_reads':0,'http_requests':0,
        'production_mapping_modified':False,'player_identifiers_exported':False}
    if cache_zip is not None:
        public=inspect_public_schemes(cache_zip,vehicle)
        indexed=indexed_candidate(cache_zip)
        if indexed['indexed_asset']['astc_size_bytes']!=current['bundle_bytes']:
            raise CarMetadataError('uploaded CarMetadata size does not match db34011 index')
        result['verified_public_milestone_scheme']=public
        result['source_database_34011_bundle_version']=indexed['indexed_asset']['version']
        result['milestone_predicate_statically_supported']=(public['matching_schemes_found']==1)
        result['milestone_predicate_actual_runtime_return_captured']=False
    if apk is not None:
        meta,native=_read_native(apk)
        result['native_carinfo_load_and_flag_evidence']=native_provenance(meta,native)
    if visual_bundle is not None:
        visual,unlocks=parse_asset(unpack_unityfs(visual_bundle.read_bytes()))
        paints,appended=conditional_list(visual['CarPaintIDs'],unlocks['AllUnlockables']['carPaintIDs'])
        if not 0<=paint_index<len(paints):
            raise CarMetadataError('paint index outside reconstructed list')
        cid=paints[paint_index]
        label=None
        if source_catalog:
            source=json.loads(source_catalog.read_text('utf8'))
            if source.get('database_version')!='34011':
                raise CarMetadataError('expected public source catalog version 34011')
            ids=[s for s in source['individual_source_ids'] if s.get('slot')=='paint'
                and s.get('numeric_id')==cid and s.get('source_library') in
                ('CarPaintLibrary','CarTunerStarsPaintLibrary')]
            if len(ids)!=1:raise CarMetadataError('ambiguous source library paint label')
            label=ids[0]['source_label']
        result['conditional_paint_replay']={
            'paint_index':paint_index,'paint_id':cid,'library_label':label,
            'base_list_count':len(visual['CarPaintIDs']),
            'unique_unlockables_appended':len(appended),
            'combined_list_length':len(paints),
            'car_tuner_stars_record_flag_is_false':not current['carinfo']['is_tuner_stars_car'],
            'exact_loaded_runtime_list_not_proven':True,'production_verified':False}
    return result


def main(argv:list[str]|None=None)->int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--car-metadata-bundle',required=True,type=Path)
    p.add_argument('--visual-bundle',type=Path)
    p.add_argument('--cache-zip',type=Path)
    p.add_argument('--apk',type=Path)
    p.add_argument('--source-catalog',type=Path)
    p.add_argument('--vehicle',default='Ford_Mustang302_1970')
    p.add_argument('--paint-index',type=int,default=15)
    p.add_argument('--output',required=True,type=Path)
    a=p.parse_args(argv)
    if a.output.exists() or a.output.is_symlink():p.error('refusing to overwrite output')
    data=inspect(a.car_metadata_bundle,a.visual_bundle,a.cache_zip,a.apk,a.source_catalog,a.vehicle,a.paint_index)
    a.output.write_text(json.dumps(data,indent=2,sort_keys=True)+'\n','utf8')
    print('CarInfo IsTunerStarsCar =',data['record_is_tuner_stars_car'])
    if 'conditional_paint_replay' in data:
        print('Conditional paint ID =',data['conditional_paint_replay']['paint_id'])
    return 0

if __name__=='__main__':raise SystemExit(main())
