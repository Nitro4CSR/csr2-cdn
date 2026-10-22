"""Dev55: offline native paint-list branch and source-cache audit (not a resolver).

Pinned to CSR2 6.8.0 native bytes; metadata values and private crew entries
are never emitted. No network, login, gameplay or index-to-ID assumptions.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit
from zipfile import ZipFile
from .dev54_initial_paint_setup import _resolve, _word_at, _witness, _decode_bl
from .dev48_native_paint_methods import _META_PATH, _SO_PATH, _MAX_METADATA, _MAX_NATIVE
from .dev52_car_paint_list_native import _MAX_APK


def _cond_target(word:int, pc:int)->int|None:
    if word & 0xff000010 != 0x54000000:return None
    signed=(word>>5)&0x7ffff
    if signed & 0x40000:signed-=0x80000
    return pc+signed*4


def native_audit(metadata:bytes,native:bytes)->dict:
    methods=_resolve(metadata,native)  # fail closed on native SHA-256
    method=methods[('CarVisuals','Setup')]
    if int(method['rva'],16)!=0x380275c:raise ValueError('Setup RVA changed')
    _witness(method,{
       0x38029a4:0xb9410808, 0x38029a8:0x7100291f, 0x38029ac:0x54000f08,
       0x38029b0:0x52800029, 0x38029b4:0x1ac82129, 0x38029b8:0x5280c08a,
       0x38029bc:0x6a0a013f, 0x38029c0:0x54000e60,
       0x38029c4:0xb9411e68, 0x38029c8:0x37f80748,
       0x38029d4:0xb9401d08, 0x38029d8:0x12b00009,
       0x38029dc:0x6b09011f, 0x38029e0:0x540006c0,
       0x3802a44:0x9449c00d, 0x3802a48:0x3100041f,
       0x3802aa8:0xb9002101, 0x3802b8c:0x2a0803e0,
       0x3802b94:0x97f1ca3c, 0x3802b98:0x36000ba0,
       0x38036f4:0xb9406d09, 0x3803704:0xb9401929,
       0x380370c:0xb9006d09,
    })
    for addr,target in ((0x38029ac,0x3802b8c),(0x38029c0,0x3802b8c),(0x38029e0,0x3802ab8)):
        if _cond_target(_word_at(method,addr),addr)!=target:
            raise ValueError('source branch destination changed')
    if _decode_bl(_word_at(method,0x3802b94),0x3802b94)!=0x3475484:
        raise ValueError('IsIAP native call target changed')
    opcode=_word_at(method,0x38029b8)
    if opcode & 0xffe0001f != 0x5280000a:raise ValueError('not movz w10 immediate')
    mask=(opcode>>5)&0xffff
    values=[i for i in range(11) if mask&(1<<i)]
    if values != [2,9,10]:raise ValueError('branch enum set changed')
    return {
      'status':'dev55_pinned_native_source_branch_audit',
      'client':'CSR2 6.8.0',
      'method':{'name':'CarVisuals.Setup','rva':method['rva'],'sha256':method['sha256']},
      'garage_car_source_extension_offset':'0x108',
      'special_branch_enum_values':values,
      'enum_value_meanings_verified':False,
      'other_source_extensions_test_IsIAP':True,
      'branch_checks_current_paint_index_sign':True,
      'branch_checks_visual_paint_id_sentinel':True,
      'observed_visual_id_sentinel_candidate':2147483647,
      'branches_can_append_to_car_local_paint_list':True,
      'setup_can_adjust_index_using_list_count':True,
      'runtime_car_paint_id_order_recovered':False,
      'index_0_resolved':False,'index_15_resolved':False,
      'transparent_interpretation_withdrawn':True,
      'production_resolver_changed':False,
    }


def inspect_apk(apk:Path)->dict:
    if apk.is_symlink() or not apk.is_file() or apk.stat().st_size > _MAX_APK:
        raise ValueError('APK unavailable, linked, or oversized')
    with ZipFile(apk) as archive:
        chunks=[]
        for name,cap in ((_META_PATH,_MAX_METADATA),(_SO_PATH,_MAX_NATIVE)):
            item=archive.getinfo(name)
            if not 64<item.file_size<=cap or item.compress_size>cap:
                raise ValueError('invalid APK native file size')
            chunks.append(archive.read(item))
    return native_audit(*chunks)


def _verified_member(z:ZipFile,entries:list,member:str,limit:int)->bytes:
    path=member.removeprefix('endpoint-cache/')
    records=[x for x in entries if isinstance(x,dict) and x.get('file')==path]
    if len(records)!=1:raise ValueError('cache manifest member absent or duplicated')
    info=z.getinfo(member)
    if info.file_size>limit or info.file_size != records[0].get('bytes'):
        raise ValueError('cache member size mismatch')
    data=z.read(info)
    if hashlib.sha256(data).hexdigest()!=records[0].get('sha256'):
        raise ValueError('cached file digest mismatch')
    return data


def inspect_cache(cache:Path)->dict:
    if cache.is_symlink() or not cache.is_file() or cache.stat().st_size>225_000_000:
        raise ValueError('cache ZIP unavailable, linked or oversized')
    with ZipFile(cache) as z:
        names=z.namelist()
        if len(names)!=len(set(names)):raise ValueError('duplicate archive names')
        info=z.getinfo('endpoint-cache/manifest.json')
        if info.file_size>2_000_000:raise ValueError('manifest oversized')
        manifest=json.loads(z.read(info))
        entries=manifest['responses']
        if not isinstance(entries,list) or len(entries)>10000:raise ValueError('invalid manifest entries')
        names=[p for p in names if p.startswith('endpoint-cache/public/') and p.endswith('.json')]
        if len(names)>512:raise ValueError('too many public descriptors')
        assets=[]
        for name in names:
            desc=json.loads(_verified_member(z,entries,name,16384))
            if desc.get('status_code')!=200:continue
            url=desc.get('url')
            if not isinstance(url,str) or len(url)>2000:raise ValueError('invalid public URL')
            parsed=urlsplit(url)
            if parsed.scheme!='https' or parsed.hostname!='csr2.cdn.zynga.com':continue
            asset=parsed.path.rsplit('/',1)[-1]
            if asset:assets.append(asset)
        blocks={}
        for key in ('CarSpecificProperties','CarAdditionalVisuals'):
            path=f'endpoint-cache/metadata/{key}.meta'
            data=json.loads(_verified_member(z,entries,path,15_000_000))
            block=data.get(key)
            if not isinstance(block,dict):raise ValueError('unexpected metadata block format')
            if key=='CarSpecificProperties':
                records=block.get('PropertiesByCarId')
                if not isinstance(records,dict):raise ValueError('unexpected per-car registry')
                count=len(records)
            else:count=len(block)
            blocks[key]={'entry_count':count,'ordered_paint_ID_list_schema_verified':False}
        known_paint=sum(n.startswith(('CarPaintLibrary.ASTC.','CarTunerStarsPaintLibrary.ASTC.')) for n in assets)
        # Constrained known filename patterns; nonmatches do not imply no such assets exist.
        model_visual=sum(n.startswith(('CarVisuals_','CarVisuals.','assets_cars_','assets_carvisuals_')) for n in assets)
        return {
          'status':'dev55_redacted_public_cache_scope',
          'official_public_bundle_descriptors':len(assets),
          'paint_libraries_present':known_paint,
          'model_visual_assets_matching_known_patterns':model_visual,
          'candidate_filename_patterns_exhaustive':False,
          'metadata_blocks':blocks,
          'car_specific_ordered_paint_list_identified':False,
          'player_or_model_keys_emitted':False,
          'private_game_payloads_read':False,
        }


def inspect(apk:Path,cache:Path|None=None)->dict:
    result={'native':inspect_apk(apk)}
    if cache is not None:result['cache']=inspect_cache(cache)
    result.update(network_requests=0,gameplay_reads=0,paint_0_resolved=False,paint_15_resolved=False,production_mappings_changed=False)
    return result


def main(argv:list[str]|None=None)->int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--apk',required=True,type=Path)
    p.add_argument('--cache-zip',type=Path)
    p.add_argument('--output',required=True,type=Path)
    a=p.parse_args(argv)
    if a.output.exists() or a.output.is_symlink():p.error('refuses to overwrite existing output')
    try:
        report=inspect(a.apk,a.cache_zip)
        with a.output.open('x',encoding='utf8') as out:
            json.dump(report,out,sort_keys=True,indent=2)
            out.write('\n')
    except (ValueError,OSError,KeyError) as e:p.error(str(e))
    print('Dev55: branch conditions verified; car-local paint indices 0 and 15 unresolved.')
    return 0

if __name__=='__main__':raise SystemExit(main())
