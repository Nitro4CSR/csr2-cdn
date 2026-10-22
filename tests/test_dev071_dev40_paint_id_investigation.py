"""Dev40: exact identity, operator-label, namespace and bounded CDN tests."""
from __future__ import annotations

import hashlib
import json

import pytest

from csr2cdn._research.dev40_paint_id_investigation import (
    validate_evidence, analyze, fetch_current_wrap, main,
)
from csr2cdn._research.dev29_public_cdn_forensics import PublicCDNProbeError
from test_dev16_native_visual_extensions import _synthetic
from test_dev071_dev29_public_cdn_forensics import Response, Session, ORIGIN, BRANCH

LIBRARY_TO_SLOT = {
    'CarPaintLibrary': 'paint', 'CarInteriorLibrary': 'interior',
    'CarCalliperLibrary': 'calliper', 'CarTunerStarsPaintLibrary': 'paint',
    'CarTunerStarsInteriorLibrary': 'interior', 'CarTunerStarsCalliperLibrary': 'calliper',
}


def fixtures(tmp_path):
    sha = {k: hashlib.sha256(k.encode()).hexdigest() for k in LIBRARY_TO_SLOT}
    cat = {
        'status': 'public_source_id_catalog_not_unresolved_roster_ids',
        'branch': BRANCH, 'database_version': '34011',
        'source_sha256': sha, 'contains_player_or_roster_data': False,
        'mapping_promoted': False,
        'individual_source_ids': [],
    }
    values = {
        'CarPaintLibrary': [(1, 'White')],
        'CarTunerStarsPaintLibrary': [(1000001, 'Blue')],
        'CarInteriorLibrary': [(0, 'Argento Grey'), (15, 'Bitter Chocolate')],
        'CarTunerStarsInteriorLibrary': [(1000002, 'Grey')],
        'CarCalliperLibrary': [(0, 'Black'), (15, 'Grigio Silverstone')],
        'CarTunerStarsCalliperLibrary': [(1000003, 'Red')],
    }
    for k, pairs in values.items():
        for code, name in pairs:
            cat['individual_source_ids'].append({
                'slot': LIBRARY_TO_SLOT[k], 'numeric_id': code, 'source_library': k,
                'source_label': name, 'additional_source_labels': [], 'source_category': 'All',
                'vehicle_eligibility_verified': False,
                'unresolved_roster_id': 'unknown_without_saved_roster',
            })
    summary = {
        'status': 'current_release_public_cosmetic_sources_validated',
        'branch': BRANCH, 'database_version': '34011', 'source_sha256': sha,
        'source_record_counts': {k: len(p) for k,p in values.items()},
        'source_total_records': len(cat['individual_source_ids']),
        'gameplay_read_count': 0, 'authentication_used': False,
    }
    received = {
        'status':'received_roster_numeric_ids_absent_from_source_libraries',
        'source_branch': BRANCH, 'source_database_version': '34011', 'source_sha256': sha,
        'individual_absent_received_ids': [
            {'attribute': 'paint', 'received_numeric_id':0, 'occurrences':8,
             'tnr_model_syntax_occurrences':1, 'other_or_unknown_model_occurrences':7},
            {'attribute': 'paint', 'received_numeric_id':15, 'occurrences':1,
             'tnr_model_syntax_occurrences':0, 'other_or_unknown_model_occurrences':1},
        ],
        'coverage_by_attribute': {'paint': {'absent_from_sources':9}},
        'unique_attribute_id_pairs_absent': 2,
        'total_absent_received_occurrences': 9,
        'test_secret': 'PRIVATE_DONT_EXPORT',
    }
    palette = {
        'status': 'received_paint_id_vs_separate_color_palette_checked',
        'roster_source_branch': BRANCH, 'roster_source_database_version': '34011',
        'palette_branch': BRANCH, 'palette_database_version': '34011',
        'palette_asset_version': '604', 'palette_sha256':'a'*64,
        'same_database_version_as_roster_sources': True,
        'source_paint_library_absence_unchanged': True,
        'numeric_palette_overlap_is_not_paint_name_mapping': True,
        'mapping_promoted': False, 'gameplay_read_count': 0, 'authentication_used': False,
        'individual_unmatched_received_paint_ids': [
            {'received_paint_id': 0, 'occurrences':8,
             'tnr_model_syntax_occurrences':1, 'other_or_unknown_model_occurrences':7,
             'present_in_color_palette':True, 'palette_name':'Transparent',
             'paint_to_color_namespace_join_verified':False},
            {'received_paint_id': 15, 'occurrences':1,
             'tnr_model_syntax_occurrences':0, 'other_or_unknown_model_occurrences':1,
             'present_in_color_palette':False, 'palette_name':None,
             'paint_to_color_namespace_join_verified':False},
        ],
    }
    out={}
    for key,doc in [('catalog',cat), ('summary',summary),('received',received),('palette',palette)]:
        p = tmp_path / (key+'.json');p.write_text(json.dumps(doc), encoding='utf-8');out[key]=p
    return out


def test_operator_approved_transparent_zero_preserves_unresolved_paint_and_cross_slot(tmp_path):
    files=fixtures(tmp_path)
    received,palette,meta,idx,checked=validate_evidence(files['received'],files['palette'],files['catalog'],files['summary'])
    result=analyze(received,palette,meta,idx,checked,accept_transparent_zero=True)
    a,b = result['individual_received_paint_ids']
    assert a['received_numeric_id']==0 and a['operator_approved_display_label']=='Transparent'
    assert a['paint_library_status']=='absent_from_both_paint_libraries'
    assert a['paint_to_palette_join_verified'] is False
    assert b['received_numeric_id']==15 and b['operator_approved_display_label'] is None
    assert len(b['other_attribute_matches_not_paint'])==2
    assert {x['attribute'] for x in b['other_attribute_matches_not_paint']}=={'interior','calliper'}
    assert result['production_mapping_promoted'] is False
    assert result['network_requests']==0
    assert 'PRIVATE_DONT_EXPORT' not in json.dumps(result)


def test_display_alias_is_opt_in_not_auto_promotion(tmp_path):
    files=fixtures(tmp_path)
    r,p,m,i,c=validate_evidence(files['received'],files['palette'],files['catalog'],files['summary'])
    report=analyze(r,p,m,i,c,accept_transparent_zero=False)
    assert report['individual_received_paint_ids'][0]['operator_approved_display_label'] is None
    assert report['transparent_zero_operator_acceptance_explicit'] is False
    assert report['production_mapping_promoted'] is False


def test_source_palette_name_not_transparent_refuses_user_alias(tmp_path):
    files=fixtures(tmp_path)
    p=files['palette'];d=json.loads(p.read_text());d['individual_unmatched_received_paint_ids'][0]['palette_name']='Other'
    p.write_text(json.dumps(d))
    r,pal,m,i,c=validate_evidence(files['received'],files['palette'],files['catalog'],files['summary'])
    report=analyze(r,pal,m,i,c,accept_transparent_zero=True)
    assert report['individual_received_paint_ids'][0]['operator_approved_display_label'] is None


@pytest.mark.parametrize('change', ['db','wrong_counts','bad_join','collision','bad_hash','different_palette_version'])
def test_contradictory_evidence_rejected(tmp_path,change):
    f=fixtures(tmp_path)
    if change == 'db':
        p=f['palette'];d=json.loads(p.read_text());d['palette_database_version']='34012'
    elif change == 'wrong_counts':
        p=f['palette'];d=json.loads(p.read_text());d['individual_unmatched_received_paint_ids'][0]['occurrences']=9
    elif change == 'bad_join':
        p=f['palette'];d=json.loads(p.read_text());d['individual_unmatched_received_paint_ids'][0]['paint_to_color_namespace_join_verified']=True
    elif change == 'collision':
        p=f['catalog'];d=json.loads(p.read_text());d['individual_source_ids'][0]['numeric_id']=15
    elif change == 'bad_hash':
        p=f['received'];d=json.loads(p.read_text());d['source_sha256']['CarPaintLibrary']='b'*64
    elif change == 'different_palette_version':
        p=f['palette'];d=json.loads(p.read_text());d['roster_source_database_version']='34012'
    p.write_text(json.dumps(d))
    with pytest.raises(ValueError):
        validate_evidence(f['received'],f['palette'],f['catalog'],f['summary'])


def wrap_session(raw=None):
    raw=raw or _synthetic('CarWrapLibrary')
    doc=[{'version':'34011'}, [{'code':'CarWrapLibrary','version':'777','type':'31',
                                'sizes':{'ASTC':len(raw)}}]]
    return Session({f'{ORIGIN}/asset_database_{BRANCH}.version':Response(b'{"version":"34011"}'),
                    f'{ORIGIN}/asset_database.34011.json':Response(json.dumps(doc).encode()),
                    f'{ORIGIN}/ANDROID/ASTC/CarWrapLibrary.ASTC.777':Response(raw)})


def test_wrap_probe_uses_only_three_public_gets_and_cross_slot_stays_untrusted(tmp_path):
    s=wrap_session()
    raw, evidence=fetch_current_wrap(BRANCH,session=s)
    assert len(s.calls)==3 and evidence['network_requests']==3
    assert evidence['database_version']=='34011' and evidence['asset_version']=='777'
    assert all(k['allow_redirects'] is False and k['stream'] is True for _,k in s.calls)
    f=fixtures(tmp_path)
    r,p,m,i,c=validate_evidence(f['received'],f['palette'],f['catalog'],f['summary'])
    out=analyze(r,p,m,i,c,accept_transparent_zero=True,wrap_bytes=raw,wrap_evidence=evidence)
    assert out['individual_received_paint_ids'][1]['wrap_source']=={
        'checked':True,'present':False,'name':None,'not_paint_mapping':True}
    assert out['production_mapping_promoted'] is False
    assert out['network_requests']==3


def test_wrap_probe_rejects_bad_branch_before_any_get():
    s=wrap_session()
    with pytest.raises(ValueError):fetch_current_wrap('../bad',session=s)
    assert s.calls==[]


def test_wrap_probe_missing_source_fails_after_two_gets():
    s=wrap_session();p=f'{ORIGIN}/asset_database.34011.json'
    s.mapping[p]=Response(json.dumps([{'version':'34011'},[]]).encode())
    with pytest.raises(PublicCDNProbeError):fetch_current_wrap(BRANCH,session=s)
    assert len(s.calls)==2


def test_wrap_probe_corrupt_bundle_is_rejected(tmp_path):
    s=wrap_session();p=f'{ORIGIN}/ANDROID/ASTC/CarWrapLibrary.ASTC.777'
    raw=s.mapping[p].payload
    s.mapping[p]=Response(b'\0'*len(raw))
    with pytest.raises((ValueError, PublicCDNProbeError)):fetch_current_wrap(BRANCH,session=s)
    assert len(s.calls)==3


def test_cli_offline_success_rejects_overwrite_no_network(tmp_path,capsys,monkeypatch):
    files=fixtures(tmp_path)
    monkeypatch.setattr('socket.socket.connect',lambda *_: pytest.fail('offline made network call'))
    args=['--received-report',str(files['received']),'--palette-report',str(files['palette']),
          '--catalog',str(files['catalog']),'--summary',str(files['summary']),
          '--accept-transparent-zero','--output',str(tmp_path/'result.json')]
    assert main(args)==0
    result=json.loads((tmp_path/'result.json').read_text())
    assert result['network_requests']==0
    assert result['individual_received_paint_ids'][0]['operator_approved_display_label']=='Transparent'
    with pytest.raises(SystemExit):
        main(args)  # overwrite is rejected by argparse
    assert 'PRIVATE_DONT_EXPORT' not in capsys.readouterr().out


def test_cli_local_wrap_bundle_without_network(tmp_path, monkeypatch, capsys):
    files=fixtures(tmp_path)
    wrap=tmp_path/'wrap.bin';wrap.write_bytes(_synthetic('CarWrapLibrary'))
    monkeypatch.setattr('socket.socket.connect',lambda *_: pytest.fail('offline made network call'))
    args=['--received-report',str(files['received']),'--palette-report',str(files['palette']),
          '--catalog',str(files['catalog']),'--summary',str(files['summary']),
          '--wrap-bundle',str(wrap)]
    assert main(args)==0
    result=json.loads(capsys.readouterr().out)
    assert result['individual_received_paint_ids'][0]['wrap_source']['checked'] is True
    assert result['network_requests']==0
