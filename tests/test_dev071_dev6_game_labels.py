"""Dev6: game translation preferences, visual libraries, CDN cache, privacy."""
import json

import pytest

from csr2cdn.game_labels import (CarNameStyle, GameCarTranslations,
    GameVisualLibrary, game_label_report, metadata_library_inventory)
from csr2cdn.crew_bulk_validation import bulk_report, main
from csr2cdn.crew_optional_data import CrewOptionalSnapshot
from csr2cdn._service_reads import StandingRange
from csr2cdn.metadata import MetadataCache
from csr2cdn.service_models import OwnCrew, CrewMembers

PRIVATE = 'HIDDEN_MEMBER_NAME_6'

def names():
    return GameCarTranslations.from_manifest({
        'format':'csr2cdn.car-translations.v1', 'records': [
            {'model_key':'Toyota_Supra_2020', 'SHORT':'Supra',
             'MEDIUM':'Toyota GR Supra', 'LONG':'2020 Toyota GR Supra'},
            {'model_key':'Bugatti_Chiron_2018','SHORT':'Chiron'},
        ]})

def visuals():
    return GameVisualLibrary.from_manifest({
        'format':'csr2cdn.visual-code-library.v1','records': [
            {'model_key':'Toyota_Supra_2020','slot':'paint','code':0,
             'name':'Pearl white','source_library':'CarPaintLibrary'},
            {'model_key':'Toyota_Supra_2020','slot':'wheel','code':'wA',
             'name':'Wheels A','source_library':'CarWheelsLibrary'},
        ]})

def wire():
    own={'crew_uid':'CREW_SENSITIVE', 'members':2}
    roster={'crew_uid':'CREW_SENSITIVE','scores':[
        {'player_uid':'PRIVATE_A','name':PRIVATE,'current_car':'Toyota_Supra_2020',
         'car_paint_id':0,'car_wheel_name':'wA','cc_contrib':20},
        {'player_uid':'PRIVATE_B','name':'PRIVATE_B_NAME','current_car':'Bugatti_Chiron_2018',
         'car_paint_id':1,'car_wheel_name':'wB','cc_contrib':30},
    ]}
    common={'scores':[{'crew_id':'CREW_SENSITIVE','name':'CREW_PRIVATE','rank':99,'score':50}]}
    return own,roster,common,common

def snapshot():
    own,roster,_,_=wire()
    return CrewOptionalSnapshot.from_reads(OwnCrew.from_response(own), CrewMembers.from_response('CREW_SENSITIVE',roster))

@pytest.mark.parametrize('style,expected',[('SHORT','Supra'),('MEDIUM','Toyota GR Supra'),('LONG','2020 Toyota GR Supra'),('medium','Toyota GR Supra')])
def test_car_name_length_selection(style,expected):
    assert names().match('Toyota_Supra_2020').choose(style) == expected
    assert CarNameStyle.coerce(style).value == style.upper()

def test_medium_default_does_not_fallback_and_exact_match():
    assert names().match('Bugatti_Chiron_2018').choose() is None
    assert names().match('Bugatti_Chiron_2018').choose('SHORT') == 'Chiron'
    assert names().match('toyota_supra_2020') is None
    assert names().match(None) is None

def test_bad_styles_fail_closed():
    for value in ['MEDIUM ', 'VERY_LONG', '', 5, None]:
        with pytest.raises(ValueError): CarNameStyle.coerce(value)

@pytest.mark.parametrize('record',[{}, {'model_key':'X', 'SHORT':' '},
                                  {'model_key':'X','SHORT':3},
                                  {'model_key':'X','LONG':'bad\nname'}])
def test_bad_translation_records_rejected(record):
    with pytest.raises(ValueError):
        GameCarTranslations.from_manifest({'format':'csr2cdn.car-translations.v1','records':[record]})

def test_translation_ambiguous_and_fake_schema_rejected():
    with pytest.raises(ValueError):
        GameCarTranslations.from_manifest({'format':'csr2cdn.car-translations.v1',
           'records':[{'model_key':'X','SHORT':'x'}, {'model_key':'X','MEDIUM':'x'}]})
    with pytest.raises(ValueError):
        GameCarTranslations.from_manifest({'translations':{'X':{'MEDIUM':'x'}}})

def test_visual_code_type_exact_including_zero():
    v=visuals()
    assert v.match('Toyota_Supra_2020','paint',0).name=='Pearl white'
    assert v.match('Toyota_Supra_2020','wheel','wA').name=='Wheels A'
    assert v.match('Toyota_Supra_2020','paint','0') is None
    assert v.match('Toyota_Supra_2020','paint',False) is None
    assert v.match('Toyota_Supra_2020','paint',1) is None
    assert v.match('Toyota_Supra_2020','wheel','wa') is None

def test_visual_code_duplicate_and_invalid_label():
    d={'format':'csr2cdn.visual-code-library.v1','records':[{
       'model_key':'X','slot':'paint','code':1,'name':'Color','source_library':'CarPaintLibrary'}]}
    with pytest.raises(ValueError,match='ambiguous'):
        GameVisualLibrary.from_manifest({**d,'records': d['records']*2})
    for key,value in [('code', True),('slot','unknown'),('name','\n'),('source_library','')]:
        invalid=dict(d['records'][0]); invalid[key]=value
        with pytest.raises(ValueError):
            GameVisualLibrary.from_manifest({**d,'records':[invalid]})

def test_optional_metadata_hash_contract():
    x={'format':'csr2cdn.visual-code-library.v1','records':[{'model_key':'X','slot':'paint',
       'code':0,'name':'Color','source_library':'CarPaintLibrary','metadata_hash':'a'*32}]}
    assert GameVisualLibrary.from_manifest(x).records[0].source_hash=='a'*32
    x['records'][0]['metadata_hash']='wrong'
    with pytest.raises(ValueError): GameVisualLibrary.from_manifest(x)

def test_bulk_label_coverage_hides_member_values_by_default():
    r=game_label_report(snapshot(),names=names(),visuals=visuals())
    string=json.dumps(r)
    assert r['car_name_style']=='MEDIUM'
    assert r['car_names_resolved']==1
    assert r['visual_codes_present']['paint']==2
    assert r['visual_codes_resolved']['paint']==1
    assert r['visual_codes_resolved']['wheel']==1
    for secret in (PRIVATE, 'Pearl white','Supra','Toyota GR Supra','CREW_SENSITIVE','wA'):
        assert secret not in string
    r=game_label_report(snapshot(),names=names(),visuals=visuals(),show_members=True)
    assert r['member_labels'][0]['car_name']=='Toyota GR Supra'
    assert r['member_labels'][0]['visual_names']['paint']['name']=='Pearl white'
    assert r['member_labels'][1]['car_name'] is None

def test_bulk_report_preserves_existing_sections_and_adds_labels():
    report=bulk_report(*wire(), ranges=StandingRange(top=20, before=10, after=10, offset=0),
                       game_names=names(), game_visuals=visuals(), car_name_style='LONG')
    assert report['gcc']['common']['own_crew_score']==50
    assert report['optional']['member_rows']==2
    assert report['game_labels']['car_name_style']=='LONG'
    assert 'member_labels' not in report['game_labels']
    assert PRIVATE not in json.dumps(report)

def test_game_metadata_cache_offline_inventory(tmp_path):
    cache=MetadataCache(tmp_path)
    assert all(not x['cached'] for x in metadata_library_inventory(cache)['blocks'].values())
    (tmp_path/'CarCustomizationParameters.meta').write_text('{"CarCustomizationParameters":{"items":[1]}}')
    cache.save_hashes({'CarCustomizationParameters':'a'*32})
    result=metadata_library_inventory(cache)
    item=result['blocks']['CarCustomizationParameters']
    assert item=={'cached':True,'metadata_hash_available':True,'decoded_json_type':'dict'}
    assert json.dumps(result).find('"items"')==-1
    with pytest.raises(ValueError):
        metadata_library_inventory(cache,('SecretData',))

def test_cli_dry_run_no_network(capsys):
    assert main(['--car-name-style','SHORT','--car-translations-json','does-not-exist'])==0
    out=json.loads(capsys.readouterr().out)
    assert out['network_requests']==0
    assert out['planned_live_requests']==4

def test_cli_offline_four_fixtures_with_translations_and_visuals(tmp_path, capsys):
    files=[]
    for i,raw in enumerate(wire()):
        p=tmp_path/f'wire{i}.json';p.write_text(json.dumps(raw));files.append(p)
    p_names=tmp_path/'names.json'
    p_names.write_text(json.dumps({'format':'csr2cdn.car-translations.v1','records':[
            {'model_key':'Toyota_Supra_2020','MEDIUM':'Toyota GR Supra','LONG':'Full name'}]}))
    p_visual=tmp_path/'visuals.json'
    p_visual.write_text(json.dumps({'format':'csr2cdn.visual-code-library.v1','records':[
             {'model_key':'Toyota_Supra_2020','slot':'paint','code':0,
              'name':'Pearl white','source_library':'CarPaintLibrary'}]}))
    cache=tmp_path/'cache';cache.mkdir()
    args=[k for p,k in zip(files,('--own-json','--members-json','--gcc-common-json','--gcc-experimental-json')) for k in (k,str(p))]
    args+=['--car-translations-json',str(p_names),'--visual-library-json',str(p_visual),
           '--metadata-cache-dir',str(cache)]
    assert main(args)==0
    result=json.loads(capsys.readouterr().out)
    assert result['game_labels']['car_names_resolved']==1
    assert result['game_labels']['visual_codes_resolved']['paint']==1
    assert result['metadata_cdn_inventory']['network_requests']==0
    assert PRIVATE not in json.dumps(result)
    assert 'Pearl white' not in json.dumps(result)
    assert main(args+['--car-name-style','LONG','--show-members'])==0
    priv=json.loads(capsys.readouterr().out)
    assert priv['game_labels']['member_labels'][0]['car_name']=='Full name'
